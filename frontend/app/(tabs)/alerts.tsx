import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Modal, KeyboardAvoidingView, Platform } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { api } from "@/src/api";
import { Input } from "@/src/Input";
import { Button } from "@/src/Button";
import { ToastHost, toast } from "@/src/Toast";
import { Badge } from "@/src/parts";
import { colors, spacing, radius } from "@/src/theme";

const KINDS = [
  { id: "price_above", label: "Price above", icon: "trending-up" },
  { id: "price_below", label: "Price below", icon: "trending-down" },
  { id: "earnings", label: "Earnings approaching", icon: "calendar" },
];

export default function Alerts() {
  const insets = useSafeAreaInsets();
  const [items, setItems] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [ticker, setTicker] = useState("");
  const [kind, setKind] = useState("price_above");
  const [threshold, setThreshold] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try { const r = await api("/api/alerts"); setItems(r.items || []); } catch {}
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const add = async () => {
    if (!ticker.trim()) { toast("Enter a ticker", "error"); return; }
    if ((kind === "price_above" || kind === "price_below") && !threshold.trim()) { toast("Enter a price threshold", "error"); return; }
    setLoading(true);
    try {
      await api("/api/alerts/add", {
        method: "POST",
        body: JSON.stringify({ ticker: ticker.trim().toUpperCase(), kind, threshold: threshold ? parseFloat(threshold) : null }),
      });
      // Also fire a test push for earnings alerts
      if (kind === "earnings") {
        try { await api("/api/push/earnings-reminder", { method: "POST", body: JSON.stringify({ ticker: ticker.toUpperCase(), earnings_date: new Date().toISOString().slice(0, 10) }) }); } catch {}
      }
      toast("Alert created", "success");
      setOpen(false); setTicker(""); setThreshold("");
      load();
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  const remove = async (id: string) => { try { await api(`/api/alerts/${id}`, { method: "DELETE" }); load(); } catch {} };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Alerts</Text>
            <Text style={styles.sub}>Price moves and upcoming earnings</Text>
          </View>
          <Pressable testID="add-alert" onPress={() => setOpen(true)} style={styles.addBtn}>
            <Icon name="plus" size={18} color={colors.onBrandPrimary} />
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {items.map((it) => (
          <View key={it.alert_id} style={styles.row}>
            <View style={styles.iconWrap}>
              <Icon name={KINDS.find((k) => k.id === it.kind)?.icon || "bell"} size={16} color={colors.brandPrimary} />
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={styles.rowTicker}>{it.ticker}</Text>
                <Badge text={it.active ? "active" : "paused"} kind={it.active ? "success" : "info"} />
              </View>
              <Text style={styles.rowDesc}>
                {it.kind === "earnings" ? "Earnings approaching reminder" : `${it.kind.replace("_", " ")} $${it.threshold}`}
              </Text>
            </View>
            <Pressable testID={`alert-remove-${it.alert_id}`} onPress={() => remove(it.alert_id)} style={styles.removeBtn}>
              <Icon name="trash-2" size={14} color={colors.muted} />
            </Pressable>
          </View>
        ))}

        {!items.length && (
          <View style={styles.empty}>
            <Icon name="bell-off" size={32} color={colors.muted} />
            <Text style={styles.emptyText}>No alerts yet. Create one to get notified on price moves or earnings dates.</Text>
            <Text style={styles.emptySub}>Alerts fire via push notification on signed native builds.</Text>
          </View>
        )}
      </ScrollView>

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={styles.modalWrap}>
          <View style={styles.modal}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>New alert</Text>
              <Pressable testID="close-alert" onPress={() => setOpen(false)} style={styles.removeBtn}>
                <Icon name="x" size={16} color={colors.muted} />
              </Pressable>
            </View>
            <Input testID="alert-ticker" label="Ticker" value={ticker} onChangeText={(v) => setTicker(v.toUpperCase())} placeholder="e.g., AAPL" autoCapitalize="characters" />
            <Text style={styles.chipLabel}>Trigger</Text>
            <View style={styles.chipsWrap}>
              {KINDS.map((k) => {
                const active = kind === k.id;
                return (
                  <Pressable key={k.id} testID={`alert-kind-${k.id}`} onPress={() => setKind(k.id)} style={[styles.chip, active && styles.chipActive]}>
                    <Icon name={k.icon as any} size={13} color={active ? colors.onBrandPrimary : colors.onSurface} />
                    <Text style={[styles.chipText, active && styles.chipTextActive]}>  {k.label}</Text>
                  </Pressable>
                );
              })}
            </View>
            {(kind === "price_above" || kind === "price_below") ? (
              <Input testID="alert-threshold" label="Price threshold ($)" value={threshold} onChangeText={setThreshold} keyboardType="numeric" placeholder="e.g., 350" />
            ) : null}
            <Button testID="alert-create" label="Create alert" onPress={add} loading={loading} />
          </View>
        </KeyboardAvoidingView>
      </Modal>
      <ToastHost />
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.md, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 26, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  sub: { fontSize: 13, color: colors.muted, marginTop: 2 },
  addBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },

  scroll: { padding: spacing.lg, paddingBottom: 100 },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  iconWrap: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brandSecondary, alignItems: "center", justifyContent: "center" },
  rowTicker: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  rowDesc: { fontSize: 12, color: colors.muted, marginTop: 2 },
  removeBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center" },

  empty: { alignItems: "center", padding: spacing.xl, gap: spacing.sm },
  emptyText: { color: colors.onSurface, fontSize: 14, textAlign: "center", fontWeight: "600", lineHeight: 20 },
  emptySub: { color: colors.muted, fontSize: 12, textAlign: "center", lineHeight: 17 },

  modalWrap: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.4)" },
  modal: { backgroundColor: colors.surface, padding: spacing.xl, borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingBottom: 48 },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.lg },
  modalTitle: { fontSize: 18, fontWeight: "800", color: colors.onSurface },

  chipLabel: { fontSize: 12, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.lg },
  chip: { flexDirection: "row", paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, borderWidth: 1, borderColor: colors.border, alignItems: "center" },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  chipTextActive: { color: colors.onBrandPrimary },
});
