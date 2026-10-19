import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import Icon from "@react-native-vector-icons/feather";

import { api } from "./api";
import { Button } from "./Button";
import { toast } from "./Toast";
import { Badge } from "./parts";
import { money } from "./pnl";
import { ThresholdField, toThreshold, Thr } from "./SaveStrategy";
import { colors, spacing, radius } from "./theme";

const thrText = (t: any, usd: number | null) =>
  t ? `${t.mode === "pct" ? `${t.value}%` : `$${t.value}`}${usd != null && t.mode === "pct" ? ` ($${Math.round(usd)})` : ""}` : "—";

/** Saved strategies with live P&L, progress between stop and target, inline edit/delete. */
export function StrategiesList({ items, total, onChanged }: { items: any[]; total: number; onChanged: () => void }) {
  if (!items.length) return null;
  return (
    <View testID="strategies-section">
      <View style={s.head}>
        <Text style={s.label}>Strategies · {items.length}</Text>
        <Text testID="strategies-total" style={[s.total, { color: total >= 0 ? colors.success : colors.error }]}>{money(total)}</Text>
      </View>
      {items.map((it) => <StrategyCard key={it.strategy_id} it={it} onChanged={onChanged} />)}
    </View>
  );
}

function StrategyCard({ it, onChanged }: { it: any; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<Thr>({ mode: it.target?.mode || "pct", value: it.target ? String(it.target.value) : "" });
  const [stop, setStop] = useState<Thr>({ mode: it.stop?.mode || "pct", value: it.stop ? String(it.stop.value) : "" });
  const [busy, setBusy] = useState(false);
  const m = it.mark || {};
  const pnl = m.pnl ?? 0;
  const up = pnl >= 0;
  // progress: -stop .. 0 .. +target
  const lo = -(m.stop_usd || Math.abs(it.max_loss || it.cost_basis || 1));
  const hi = m.target_usd || it.max_profit || Math.abs(it.cost_basis || 1);
  const pos = Math.max(0, Math.min(1, (pnl - lo) / (hi - lo || 1)));
  const zero = Math.max(0, Math.min(1, -lo / (hi - lo || 1)));

  const save = async () => {
    setBusy(true);
    try {
      await api(`/api/strategies/${it.strategy_id}`, { method: "PATCH", body: JSON.stringify({ target: toThreshold(target), stop: toThreshold(stop) }) });
      toast("Alerts updated", "success"); setOpen(false); onChanged();
    } catch (e: any) { toast(e.message || "Failed", "error"); } finally { setBusy(false); }
  };
  const del = async () => {
    try { await api(`/api/strategies/${it.strategy_id}`, { method: "DELETE" }); toast("Strategy removed", "info"); onChanged(); }
    catch (e: any) { toast(e.message || "Failed", "error"); }
  };

  return (
    <View testID={`strategy-${it.strategy_id}`} style={s.card}>
      <Pressable testID={`strategy-toggle-${it.strategy_id}`} onPress={() => setOpen((v) => !v)}>
        <View style={s.row}>
          <View style={{ flex: 1 }}>
            <Text style={s.name} numberOfLines={1}>{it.name}</Text>
            <Text style={s.sub}>{it.ticker} · {it.legs.length} legs · exp {it.expiration}{it.multi_expiry ? " (multi)" : ""}</Text>
          </View>
          <View style={{ alignItems: "flex-end" }}>
            <Text testID={`strategy-pnl-${it.strategy_id}`} style={[s.pnl, { color: up ? colors.success : colors.error }]}>{m.error ? "—" : money(pnl)}</Text>
            {m.pnl_pct != null ? <Text style={[s.pct, { color: up ? colors.success : colors.error }]}>{up ? "+" : ""}{m.pnl_pct}% of risk</Text> : null}
          </View>
        </View>
        <View style={s.track}>
          <View style={[s.zero, { left: `${zero * 100}%` as any }]} />
          <View style={[s.knob, { left: `${pos * 100}%` as any, backgroundColor: up ? colors.success : colors.error }]} />
        </View>
        <View style={s.row}>
          <Text style={[s.small, { color: colors.error }]}>Stop {thrText(it.stop, m.stop_usd)}</Text>
          <View style={{ flexDirection: "row", gap: 6 }}>
            {it.fired?.target ? <Badge text="Target hit" kind="success" /> : null}
            {it.fired?.stop ? <Badge text="Stop hit" kind="error" /> : null}
            {m.live === false ? <Badge text="Model mark" kind="warn" /> : null}
          </View>
          <Text style={[s.small, { color: colors.success }]}>Target {thrText(it.target, m.target_usd)}</Text>
        </View>
      </Pressable>
      {open ? (
        <View style={s.detail}>
          {it.legs.map((l: any, i: number) => (
            <Text key={i} style={s.leg}>{l.action} {l.qty}× {l.type === "Stock" ? "shares" : `${l.type} ${l.strike} · ${l.expiration}`} @ ${l.price}</Text>
          ))}
          <Text style={s.leg}>Entry {it.premium_type} {money(Math.abs(it.net_premium))} · underlying ${it.entry_underlying} → ${m.price ?? "—"}</Text>
          <View style={{ height: spacing.md }} />
          <ThresholdField label="Profit target" idPrefix={`edit-target-${it.strategy_id}`} value={target} onChange={setTarget} pctHint="% of max profit" />
          <ThresholdField label="Stop loss" idPrefix={`edit-stop-${it.strategy_id}`} value={stop} onChange={setStop} pctHint="% of max risk" />
          <Button testID={`strategy-save-${it.strategy_id}`} label="Update alerts" onPress={save} loading={busy} />
          <Pressable testID={`strategy-delete-${it.strategy_id}`} onPress={del} style={s.delete}>
            <Icon name="trash-2" size={14} color={colors.error} />
            <Text style={s.deleteText}>Delete strategy</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  label: { fontSize: 11, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1 },
  total: { fontSize: 16, fontWeight: "800", fontVariant: ["tabular-nums"] },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: spacing.sm },
  name: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.muted, marginTop: 2 },
  pnl: { fontSize: 20, fontWeight: "800", fontVariant: ["tabular-nums"] },
  pct: { fontSize: 11, fontWeight: "700" },
  track: { height: 6, borderRadius: 3, backgroundColor: colors.surfaceTertiary, marginVertical: spacing.sm },
  zero: { position: "absolute", top: -3, width: 2, height: 12, backgroundColor: colors.borderStrong },
  knob: { position: "absolute", top: -4, width: 14, height: 14, borderRadius: 7, marginLeft: -7, borderWidth: 2, borderColor: colors.surface },
  small: { fontSize: 11, fontWeight: "700" },
  detail: { marginTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.divider, paddingTop: spacing.md },
  leg: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 3 },
  delete: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 44, marginTop: spacing.sm },
  deleteText: { color: colors.error, fontWeight: "700" },
});
