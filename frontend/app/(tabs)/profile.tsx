import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

const PLANS = ["free", "simple", "advance", "expert"];
const PAID_PLANS = ["simple", "advance", "expert"];

export default function Profile() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user, refresh, signOut } = useAuth();
  const [loading, setLoading] = useState(false);
  const [pushBusy, setPushBusy] = useState(false);

  const choosePlan = async (p: string) => {
    if (PAID_PLANS.includes(p) && user?.plan !== p) {
      router.push(`/paypal?plan=${p}` as any);
      return;
    }
    setLoading(true);
    try { await api("/api/user/plan", { method: "POST", body: JSON.stringify({ plan: p }) }); await refresh(); toast(`Switched to ${p}`, "success"); }
    catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  const testPush = async () => {
    setPushBusy(true);
    try {
      const r = await api("/api/push/daily-pick", { method: "POST" });
      if (r.ok) toast(`Push sent for ${r.ticker}`, "success");
      else toast("Push blocked (available after deploy + build)", "info");
    } catch (e: any) { toast(e.message || "Push failed", "error"); }
    finally { setPushBusy(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.title}>Profile</Text>

        <View style={styles.userCard}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.name}>{user?.name}</Text>
            <Text style={styles.email}>{user?.email}</Text>
          </View>
        </View>

        <Text style={styles.section}>Current plan</Text>
        <View style={styles.planRow}>
          {PLANS.map((p) => {
            const active = user?.plan === p;
            const price = p === "simple" ? "$9" : p === "advance" ? "$29" : p === "expert" ? "$79" : "Free";
            return (
              <Pressable key={p} testID={`profile-plan-${p}`} onPress={() => choosePlan(p)} disabled={loading} style={[styles.planChip, active && styles.planChipActive]}>
                <Text style={[styles.planChipText, active && styles.planChipTextActive]}>{p.toUpperCase()}</Text>
                <Text style={[styles.planChipPrice, active && styles.planChipTextActive]}>{price}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.hint}>Paid plans checkout via PayPal (sandbox).</Text>

        <Text style={styles.section}>Notifications</Text>
        <Pressable testID="push-test-btn" onPress={testPush} disabled={pushBusy} style={styles.pushRow}>
          <Icon name="bell" size={18} color={colors.brandPrimary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.pushTitle}>Send me a sample daily pick</Text>
            <Text style={styles.pushSub}>Only works in a signed native build - earnings reminders and daily picks will fire automatically.</Text>
          </View>
          <Icon name="chevron-right" size={16} color={colors.muted} />
        </Pressable>

        <Text style={styles.section}>Onboarding</Text>
        <View style={styles.card}>
          <Row icon="check-circle" label="Plan selected" done={!!user?.plan} />
          <Row icon="file-text" label="Questionnaire" done={!!user?.questionnaire_complete} />
          <Row icon="edit-3" label="Consent signed" done={!!user?.consent_signed} />
        </View>

        <View style={{ marginTop: spacing.xl }}>
          <Button testID="profile-signout" label="Sign out" variant="ghost" onPress={signOut} />
        </View>
        <Text style={styles.disclaimer}>
          AI recommendations are educational only. Not financial advice.
        </Text>
      </ScrollView>
      <ToastHost />
    </View>
  );
}

function Row({ icon, label, done }: { icon: string; label: string; done: boolean }) {
  return (
    <View style={styles.rowItem}>
      <Icon name={icon as any} size={16} color={done ? colors.success : colors.muted} />
      <Text style={styles.rowLabel}>{label}</Text>
      <Icon name={done ? "check" : "circle"} size={14} color={done ? colors.success : colors.muted} />
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: spacing.lg, paddingBottom: 100 },
  title: { fontSize: 22, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.lg },
  userCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
  },
  avatar: { width: 48, height: 48, borderRadius: 24, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.onBrandPrimary, fontSize: 20, fontWeight: "800" },
  name: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  email: { fontSize: 13, color: colors.muted, marginTop: 2 },

  section: { fontSize: 12, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1, marginTop: spacing.xl, marginBottom: spacing.sm },
  planRow: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  planChip: { paddingHorizontal: spacing.md, height: 44, borderRadius: radius.md, backgroundColor: colors.surfaceTertiary, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  planChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  planChipText: { fontSize: 11, fontWeight: "700", color: colors.onSurface },
  planChipPrice: { fontSize: 10, color: colors.muted, fontVariant: ["tabular-nums"] },
  planChipTextActive: { color: colors.onBrandPrimary },
  hint: { color: colors.muted, fontSize: 11, marginTop: spacing.sm },
  pushRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border },
  pushTitle: { color: colors.onSurface, fontWeight: "700", fontSize: 14 },
  pushSub: { color: colors.muted, fontSize: 12, marginTop: 2 },

  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg },
  rowItem: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 10 },
  rowLabel: { flex: 1, color: colors.onSurface, fontSize: 14, fontWeight: "600" },

  disclaimer: { marginTop: spacing.xl, fontSize: 11, color: colors.muted, textAlign: "center", lineHeight: 16 },
});
