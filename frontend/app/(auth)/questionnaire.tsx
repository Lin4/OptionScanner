import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { Input } from "@/src/Input";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

type Q = { id: string; q: string; opts?: string[]; type?: "text" };
const QUESTIONS: Q[] = [
  { id: "experience", q: "What's your trading experience?", opts: ["None", "Beginner", "Intermediate", "Advanced"] },
  { id: "goal", q: "Primary investing goal?", opts: ["Income", "Growth", "Speculation", "Hedging"] },
  { id: "risk", q: "Risk tolerance?", opts: ["Conservative", "Moderate", "Aggressive"] },
  { id: "capital", q: "Approx. investable capital?", opts: ["< $5k", "$5k–$25k", "$25k–$100k", "> $100k"] },
  { id: "options_approved", q: "Options trading level?", opts: ["Not approved", "Level 1-2", "Level 3+", "Full access"] },
  { id: "income_source", q: "Primary income source", type: "text" },
];

export default function Questionnaire() {
  const insets = useSafeAreaInsets();
  const { refresh } = useAuth();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const setA = (id: string, v: string) => setAnswers((s) => ({ ...s, [id]: v }));

  const onSubmit = async () => {
    const missing = QUESTIONS.filter((q) => !answers[q.id]);
    if (missing.length) { toast(`Please answer: ${missing[0].q}`, "error"); return; }
    setLoading(true);
    try {
      await api("/api/user/questionnaire", { method: "POST", body: JSON.stringify({ answers }) });
      await refresh();
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <Text style={styles.step}>Step 2 of 3</Text>
          <Text style={styles.title}>A few questions</Text>
          <Text style={styles.subtitle}>Standard broker-style profile, 2 min.</Text>

          <View style={{ marginTop: spacing.xl, gap: spacing.lg }}>
            {QUESTIONS.map((q) => (
              <View key={q.id}>
                <Text style={styles.qlabel}>{q.q}</Text>
                {q.type === "text" ? (
                  <Input
                    testID={`q-${q.id}`}
                    label=""
                    value={answers[q.id] || ""}
                    onChangeText={(v) => setA(q.id, v)}
                    placeholder="Your answer"
                    autoCapitalize="sentences"
                  />
                ) : (
                  <View style={styles.optsRow}>
                    {q.opts!.map((o) => {
                      const active = answers[q.id] === o;
                      return (
                        <Pressable
                          key={o}
                          testID={`q-${q.id}-${o}`}
                          onPress={() => setA(q.id, o)}
                          style={[styles.opt, active && styles.optActive]}
                        >
                          <Text style={[styles.optText, active && styles.optTextActive]}>{o}</Text>
                        </Pressable>
                      );
                    })}
                  </View>
                )}
              </View>
            ))}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <Button testID="quest-submit" label="Continue" onPress={onSubmit} loading={loading} />
      </View>
      <ToastHost />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { padding: spacing.xl, paddingBottom: 120 },
  step: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12, letterSpacing: 1 },
  title: { fontSize: 28, fontWeight: "800", color: colors.onSurface, marginTop: spacing.sm, letterSpacing: -0.5 },
  subtitle: { fontSize: 14, color: colors.muted, marginTop: 4 },
  qlabel: { fontSize: 15, fontWeight: "600", color: colors.onSurface, marginBottom: spacing.sm },
  optsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  opt: {
    paddingHorizontal: spacing.md, paddingVertical: 10, borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary, borderWidth: 1, borderColor: colors.border,
  },
  optActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  optText: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  optTextActive: { color: colors.onBrandPrimary },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    paddingHorizontal: spacing.xl, paddingTop: spacing.md,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border,
  },
});
