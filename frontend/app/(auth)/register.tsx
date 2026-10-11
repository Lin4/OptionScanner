import React, { useState } from "react";
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Link } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { Button } from "@/src/Button";
import { Input } from "@/src/Input";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

export default function Register() {
  const insets = useSafeAreaInsets();
  const { signUpEmail } = useAuth();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const onSubmit = async () => {
    if (!email || !password || password.length < 6) { toast("Password must be 6+ chars", "error"); return; }
    setLoading(true);
    try { await signUpEmail(email.trim(), password, name.trim() || undefined); }
    catch (e: any) { toast(e.message || "Signup failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Link href="/(auth)/login" asChild>
            <Pressable testID="back-login" style={styles.back}>
              <Icon name="arrow-left" size={22} color={colors.onSurface} />
            </Pressable>
          </Link>
          <Text style={styles.title}>Create account</Text>
          <Text style={styles.subtitle}>Start screening smarter in seconds.</Text>

          <View style={styles.card}>
            <Input testID="reg-name" label="Name (optional)" value={name} onChangeText={setName} placeholder="Jane Trader" autoCapitalize="words" />
            <Input testID="reg-email" label="Email" value={email} onChangeText={setEmail} placeholder="you@example.com" keyboardType="email-address" />
            <Input testID="reg-password" label="Password" value={password} onChangeText={setPassword} placeholder="At least 6 characters" secureTextEntry />
            <Button testID="reg-submit" label="Create account" onPress={onSubmit} loading={loading} />
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
      <ToastHost />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, paddingBottom: spacing["2xl"] },
  back: { width: 40, height: 40, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary, marginBottom: spacing.lg },
  title: { fontSize: 28, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  subtitle: { fontSize: 14, color: colors.muted, marginTop: 4, marginBottom: spacing.xl },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl,
    borderWidth: 1, borderColor: colors.border,
  },
});
