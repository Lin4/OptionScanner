import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

const PLANS = [
  { id: "free", name: "Free", price: "$0", tagline: "Starter kit", features: ["Daily top 3 stocks", "1 ticker lookup/day", "Basic AI"] },
  { id: "simple", name: "Simple", price: "$9/mo", tagline: "For hobby traders", features: ["Top 10 stocks", "Unlimited lookups", "Day + Swing analysis"] },
  { id: "advance", name: "Advance", price: "$29/mo", tagline: "Power screening", features: ["All screeners", "Options strategies w/ Greeks", "Long-term fundamentals"] },
  { id: "expert", name: "Expert", price: "$79/mo", tagline: "Pro trading desk", features: ["Priority AI model", "Custom periods", "Full options strategies", "API access"] },
];

export default function PlanScreen() {
  const insets = useSafeAreaInsets();
  const { user, refresh } = useAuth();
  const [selected, setSelected] = useState<string>(user?.plan || "free");
  const [loading, setLoading] = useState(false);

  const onContinue = async () => {
    setLoading(true);
    try {
      await api("/api/user/plan", { method: "POST", body: JSON.stringify({ plan: selected }) });
      await refresh();
    } catch (e: any) { toast(e.message || "Failed to save plan", "error"); }
    finally { setLoading(false); }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.step}>Step 1 of 3</Text>
        <Text style={styles.title}>Pick your plan</Text>
        <Text style={styles.subtitle}>You can change this anytime.</Text>

        <View style={{ marginTop: spacing.xl, gap: spacing.md }}>
          {PLANS.map((p) => {
            const active = selected === p.id;
            return (
              <Pressable
                key={p.id}
                testID={`plan-${p.id}`}
                onPress={() => setSelected(p.id)}
                style={[styles.card, active && styles.cardActive]}
              >
                <View style={styles.cardTop}>
                  <View>
                    <Text style={styles.name}>{p.name}</Text>
                    <Text style={styles.tag}>{p.tagline}</Text>
                  </View>
                  <View style={styles.priceWrap}>
                    <Text style={styles.price}>{p.price}</Text>
                    {active && <Icon name="check-circle" size={20} color={colors.brandPrimary} style={{ marginLeft: spacing.sm }} />}
                  </View>
                </View>
                <View style={{ marginTop: spacing.sm }}>
                  {p.features.map((f) => (
                    <View key={f} style={styles.feat}>
                      <Icon name="check" size={14} color={colors.success} />
                      <Text style={styles.featText}>{f}</Text>
                    </View>
                  ))}
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + spacing.md }]}>
        <Button testID="plan-continue" label="Continue" onPress={onContinue} loading={loading} />
      </View>
      <ToastHost />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: 120 },
  step: { color: colors.brandPrimary, fontWeight: "700", marginTop: spacing.lg, fontSize: 12, letterSpacing: 1 },
  title: { fontSize: 28, fontWeight: "800", color: colors.onSurface, marginTop: spacing.sm, letterSpacing: -0.5 },
  subtitle: { fontSize: 14, color: colors.muted, marginTop: 4 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.lg, padding: spacing.lg,
  },
  cardActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandSecondary },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  name: { fontSize: 18, fontWeight: "700", color: colors.onSurface },
  tag: { fontSize: 12, color: colors.muted, marginTop: 2 },
  priceWrap: { flexDirection: "row", alignItems: "center" },
  price: { fontSize: 16, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  feat: { flexDirection: "row", alignItems: "center", gap: spacing.xs, marginTop: 4 },
  featText: { fontSize: 13, color: colors.onSurfaceSecondary, marginLeft: 6 },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    paddingHorizontal: spacing.xl, paddingTop: spacing.md,
    backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.border,
  },
});
