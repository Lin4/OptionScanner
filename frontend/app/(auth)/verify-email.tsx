import React, { useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Pressable, TextInput } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { Button } from "@/src/Button";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

const LEN = 6;

export default function VerifyEmail() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string; resend?: string }>();
  const email = String(params.email || "");
  const { verifySignup, resendSignupCode } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [wait, setWait] = useState(Number(params.resend ?? 60) || 0);
  const [focused, setFocused] = useState(false);
  const input = useRef<TextInput>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const submit = async (value = code) => {
    if (value.length !== LEN || loading) return;
    setLoading(true);
    setError("");
    try {
      await verifySignup(email, value); // root layout routes to plan / onboarding once signed in
    } catch (e: any) {
      setError(e.message || "Verification failed");
      setCode("");
      input.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  const onChange = (v: string) => {
    const digits = v.replace(/\D/g, "").slice(0, LEN);
    setCode(digits);
    if (error) setError("");
    if (digits.length === LEN) submit(digits);
  };

  const resend = async () => {
    setSending(true);
    try {
      const r = await resendSignupCode(email);
      setWait(r.resend_in || 60);
      setCode("");
      setError("");
      toast("New code sent — check your inbox", "success");
    } catch (e: any) {
      if (e.status === 404) { toast(e.message, "error"); router.replace("/(auth)/register"); return; }
      toast(e.message || "Couldn't resend the code", "error");
    } finally {
      setSending(false);
    }
  };

  const mmss = `${Math.floor(wait / 60)}:${String(wait % 60).padStart(2, "0")}`;

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Pressable testID="verify-back" accessibilityRole="button" accessibilityLabel="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/(auth)/register"))} style={styles.back}>
            <Icon name="arrow-left" size={22} color={colors.onSurface} />
          </Pressable>

          <View style={styles.badge}><Icon name="mail" size={26} color={colors.brandPrimary} /></View>
          <Text style={styles.title}>Check your email</Text>
          <Text style={styles.subtitle}>
            We sent a 6-digit code to{"\n"}<Text testID="verify-email-address" style={styles.email}>{email}</Text>
          </Text>

          <View style={styles.card}>
            <Pressable testID="verify-code-boxes" onPress={() => input.current?.focus()} style={styles.boxes} accessibilityLabel="Verification code">
              {Array.from({ length: LEN }).map((_, i) => {
                const active = focused && i === Math.min(code.length, LEN - 1);
                return (
                  <View key={i} style={[styles.box, active && styles.boxActive, !!error && styles.boxError]}>
                    <Text style={styles.digit}>{code[i] || ""}</Text>
                  </View>
                );
              })}
              <TextInput
                ref={input}
                testID="verify-code-input"
                value={code}
                onChangeText={onChange}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                keyboardType="number-pad"
                textContentType="oneTimeCode"
                autoComplete={Platform.OS === "android" ? "sms-otp" : "one-time-code"}
                maxLength={LEN}
                autoFocus
                caretHidden
                style={styles.hiddenInput}
              />
            </Pressable>

            {error ? (
              <View testID="verify-error" style={styles.errorRow}>
                <Icon name="alert-circle" size={14} color={colors.error} />
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : (
              <Text style={styles.hint}>The code expires in 10 minutes. Can&apos;t find it? Check your spam folder.</Text>
            )}

            <Button testID="verify-submit" label="Verify & create account" onPress={() => submit()} loading={loading} disabled={code.length !== LEN} />

            <View style={styles.resendRow}>
              {wait > 0 ? (
                <Text testID="verify-resend-timer" style={styles.muted}>Resend code in {mmss}</Text>
              ) : (
                <Pressable testID="verify-resend" onPress={resend} disabled={sending} hitSlop={8} style={styles.resendBtn}>
                  <Icon name="refresh-cw" size={14} color={colors.brandPrimary} />
                  <Text style={styles.link}>{sending ? "Sending…" : "Resend code"}</Text>
                </Pressable>
              )}
            </View>
          </View>

          <Pressable testID="verify-change-email" onPress={() => router.replace("/(auth)/register")} style={styles.change} hitSlop={8}>
            <Text style={styles.muted}>Wrong email? </Text>
            <Text style={styles.link}>Change it</Text>
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
      <ToastHost />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, paddingBottom: spacing["2xl"] },
  back: { width: 44, height: 44, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary, marginBottom: spacing.lg },
  badge: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brandSecondary, alignItems: "center", justifyContent: "center", marginBottom: spacing.md },
  title: { fontSize: 28, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  subtitle: { fontSize: 14, color: colors.muted, marginTop: 4, marginBottom: spacing.xl, lineHeight: 20 },
  email: { color: colors.onSurface, fontWeight: "700" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, borderWidth: 1, borderColor: colors.border },
  boxes: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  box: {
    flex: 1, aspectRatio: 0.85, maxHeight: 64, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border,
    backgroundColor: colors.surface, alignItems: "center", justifyContent: "center",
  },
  boxActive: { borderColor: colors.brandPrimary, borderWidth: 2 },
  boxError: { borderColor: colors.error },
  digit: { fontSize: 24, fontWeight: "800", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  hiddenInput: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, opacity: 0.02, color: "transparent", fontSize: 1 },
  hint: { fontSize: 12, color: colors.muted, marginTop: spacing.md, marginBottom: spacing.lg, lineHeight: 17 },
  errorRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.md, marginBottom: spacing.lg },
  errorText: { flex: 1, fontSize: 13, color: colors.error, fontWeight: "600", lineHeight: 18 },
  resendRow: { alignItems: "center", marginTop: spacing.lg, minHeight: 24, justifyContent: "center" },
  resendBtn: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: spacing.md },
  muted: { fontSize: 13, color: colors.muted },
  link: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  change: { flexDirection: "row", justifyContent: "center", alignItems: "center", marginTop: spacing.xl, minHeight: 44 },
});
