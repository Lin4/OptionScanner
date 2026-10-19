import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, ActivityIndicator, RefreshControl } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { api } from "@/src/api";
import { ToastHost, toast } from "@/src/Toast";
import { colors, spacing, radius } from "@/src/theme";

const PLANS = ["free", "simple", "advance", "expert"];

export default function Admin() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    try { const r = await api(`/api/admin/users?q=${encodeURIComponent(query)}`); setItems(r.items || []); }
    catch (e: any) { if (e.status === 403) setDenied(true); else toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => load(q), 300);
    return () => clearTimeout(t);
  }, [q, load]);

  const setPlan = async (u: any, plan: string) => {
    setBusy(u.user_id + plan);
    try {
      await api(`/api/admin/users/${u.user_id}/plan`, { method: "POST", body: JSON.stringify({ plan }) });
      setItems((p) => p.map((x) => (x.user_id === u.user_id ? { ...x, plan, tier: plan === "free" ? "trial" : plan } : x)));
      toast(`${u.email} → ${plan.toUpperCase()}`, "success");
      load(q);
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setBusy(null); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[s.header, { paddingTop: insets.top + spacing.md }]}>
        <Pressable testID="admin-back" onPress={() => (router.canGoBack() ? router.back() : router.replace("/(tabs)"))} style={s.back}>
          <Icon name="arrow-left" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Admin · Plans</Text>
      </View>
      {denied ? (
        <View style={s.center}><Icon name="lock" size={28} color={colors.muted} /><Text style={s.muted}>Admin access only.</Text></View>
      ) : (
        <ScrollView contentContainerStyle={[s.scroll, { paddingBottom: insets.bottom + 60 }]} keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={false} onRefresh={() => load(q)} />}>
          <View style={s.search}>
            <Icon name="search" size={16} color={colors.muted} />
            <TextInput testID="admin-search" value={q} onChangeText={setQ} placeholder="Search email or name" placeholderTextColor={colors.muted}
              autoCapitalize="none" style={s.input} />
          </View>
          <Text style={s.muted}>Tap a plan to switch instantly. Admin grants have no expiry and skip billing.</Text>
          {loading && !items.length ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: spacing.xl }} /> : null}
          {items.map((u) => (
            <View key={u.user_id} testID={`admin-user-${u.email}`} style={s.card}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}>
                <View style={{ flex: 1 }}>
                  <Text style={s.email} numberOfLines={1}>{u.email}</Text>
                  <Text style={s.sub}>{u.name || "—"} · now <Text style={{ fontWeight: "800", color: colors.onSurface }}>{String(u.tier).toUpperCase()}</Text>{u.plan_source ? ` via ${u.plan_source}` : ""}{u.is_admin ? " · admin" : ""}</Text>
                </View>
              </View>
              <View style={s.chips}>
                {PLANS.map((p) => {
                  const on = (u.plan || "free") === p || (p === "free" && !["simple", "advance", "expert"].includes(u.plan));
                  return (
                    <Pressable key={p} testID={`admin-plan-${u.email}-${p}`} onPress={() => !on && setPlan(u, p)} disabled={!!busy}
                      style={[s.chip, on && s.chipOn]}>
                      {busy === u.user_id + p ? <ActivityIndicator size="small" color={colors.onBrandPrimary} />
                        : <Text style={[s.chipText, on && s.chipTextOn]}>{p.toUpperCase()}</Text>}
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ))}
          {!loading && !items.length ? <Text style={s.muted}>No users found.</Text> : null}
        </ScrollView>
      )}
      <ToastHost />
    </View>
  );
}

const s = StyleSheet.create({
  header: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingBottom: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  scroll: { padding: spacing.lg },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.sm },
  search: { flexDirection: "row", alignItems: "center", gap: spacing.sm, height: 44, borderRadius: radius.md, backgroundColor: colors.surfaceTertiary, paddingHorizontal: spacing.md, marginBottom: spacing.sm },
  input: { flex: 1, fontSize: 15, color: colors.onSurface },
  muted: { fontSize: 12, color: colors.muted, marginBottom: spacing.md, textAlign: "center" },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  email: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.muted, marginTop: 2 },
  chips: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  chip: { flex: 1, height: 40, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { fontSize: 11, fontWeight: "800", color: colors.onSurface },
  chipTextOn: { color: colors.onBrandPrimary },
});
