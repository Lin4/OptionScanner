import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";

import { MetricRow } from "./parts";
import { colors, spacing, radius } from "./theme";

const big = (v: number | null | undefined) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "-" : "";
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  return `${s}$${a.toLocaleString()}`;
};
const ratio = (v: number | null | undefined) => (v == null ? "—" : Number(v).toFixed(2));

const MEASURES: [string, string, (v: any) => string][] = [
  ["market_cap", "Market Cap", big],
  ["enterprise_value", "Enterprise Value", big],
  ["trailing_pe", "Trailing P/E", ratio],
  ["forward_pe", "Forward P/E", ratio],
  ["peg_ratio", "PEG Ratio (5yr expected)", ratio],
  ["price_to_sales", "Price/Sales", ratio],
  ["price_to_book", "Price/Book", ratio],
  ["ev_to_revenue", "Enterprise Value/Revenue", ratio],
  ["ev_to_ebitda", "Enterprise Value/EBITDA", ratio],
];

export function ValuationMeasures({ m, buy, sell }: { m: Record<string, any>; buy?: number | null; sell?: number | null }) {
  return (
    <View testID="valuation-measures">
      {MEASURES.map(([k, label, fmt]) => <MetricRow key={k} label={label} value={fmt(m?.[k])} />)}
      <MetricRow label="Buy point (below)" value={buy != null ? `$${buy}` : "—"} color={colors.success} />
      <MetricRow label="Sell point (above)" value={sell != null ? `$${sell}` : "—"} color={colors.brandPrimary} />
    </View>
  );
}

const SERIES = [
  { key: "revenue", label: "Total revenue", color: colors.brandPrimary },
  { key: "net_income", label: "Net income", color: colors.success },
  { key: "operating_cash_flow", label: "Operating cash flow", color: colors.info },
  { key: "free_cash_flow", label: "Free cash flow", color: colors.warning },
];

/** Grouped bar chart of the last 3 quarters + details table. */
export function FinancialsChart({ rows, source }: { rows: any[]; source?: string }) {
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  if (!rows?.length) return <Text style={s.empty}>Quarterly filings aren&apos;t available for this ticker.</Text>;
  const shown = SERIES.filter((x) => !hidden[x.key]);
  const max = Math.max(1, ...rows.flatMap((r) => shown.map((x) => Math.abs(r[x.key] || 0))));
  const H = 140;
  return (
    <View testID="financials-chart">
      <View style={s.legend}>
        {SERIES.map((x) => (
          <Pressable key={x.key} testID={`fin-legend-${x.key}`} onPress={() => setHidden((h) => ({ ...h, [x.key]: !h[x.key] }))} style={[s.legendItem, hidden[x.key] && { opacity: 0.35 }]}>
            <View style={[s.dot, { backgroundColor: x.color }]} />
            <Text style={s.legendText}>{x.label}</Text>
          </Pressable>
        ))}
      </View>
      <View style={[s.chart, { height: H + 24 }]}>
        {rows.map((r) => (
          <View key={r.label} style={s.group}>
            <View style={[s.bars, { height: H }]}>
              {shown.map((x) => {
                const v = r[x.key] || 0;
                return <View key={x.key} style={[s.bar, { height: Math.max(2, (Math.abs(v) / max) * H), backgroundColor: v < 0 ? colors.error : x.color }]} />;
              })}
            </View>
            <Text style={s.qLabel}>{r.label}</Text>
          </View>
        ))}
      </View>

      <View style={s.table}>
        <View style={[s.tr, s.th]}>
          <Text style={[s.td, s.tdHead, { flex: 1.5 }]}>Quarter</Text>
          {rows.map((r) => <Text key={r.label} style={[s.td, s.tdHead]}>{r.label}</Text>)}
        </View>
        {[...SERIES, { key: "cash", label: "Cash on hand" }, { key: "net_margin_pct", label: "Net margin" }].map((x) => (
          <View key={x.key} testID={`fin-row-${x.key}`} style={s.tr}>
            <Text style={[s.td, { flex: 1.5, fontWeight: "700" }]}>{x.label}</Text>
            {rows.map((r) => (
              <Text key={r.label} style={[s.td, r[x.key] != null && r[x.key] < 0 && { color: colors.error }]}>
                {x.key === "net_margin_pct" ? (r[x.key] != null ? `${r[x.key]}%` : "—") : big(r[x.key])}{x.key === "cash" && r.cash_estimated ? "*" : ""}
              </Text>
            ))}
          </View>
        ))}
      </View>
      <Text style={s.note}>Quarter end: {rows.map((r) => r.end_date).join(" · ")}. {source}{rows.some((r) => r.cash_estimated) ? " *Cash estimated from cash per share." : ""}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  empty: { fontSize: 12, color: colors.muted, fontStyle: "italic" },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.sm },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 32, paddingHorizontal: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary },
  dot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 11, fontWeight: "700", color: colors.onSurface },
  chart: { flexDirection: "row", alignItems: "flex-end", justifyContent: "space-around", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, paddingTop: spacing.sm },
  group: { alignItems: "center", flex: 1 },
  bars: { flexDirection: "row", alignItems: "flex-end", gap: 3 },
  bar: { width: 12, borderTopLeftRadius: 3, borderTopRightRadius: 3 },
  qLabel: { fontSize: 10, color: colors.muted, fontWeight: "700", marginTop: 6, height: 16 },
  table: { borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, overflow: "hidden", marginTop: spacing.md },
  tr: { flexDirection: "row", paddingVertical: 8, paddingHorizontal: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  th: { backgroundColor: colors.surfaceTertiary, borderTopWidth: 0 },
  td: { flex: 1, fontSize: 11, color: colors.onSurface, fontVariant: ["tabular-nums"], textAlign: "right" },
  tdHead: { fontSize: 10, color: colors.muted, fontWeight: "800" },
  note: { fontSize: 10, color: colors.muted, fontStyle: "italic", marginTop: spacing.sm, lineHeight: 14 },
});
