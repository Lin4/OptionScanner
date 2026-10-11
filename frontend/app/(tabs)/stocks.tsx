import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { Input } from "@/src/Input";
import { ToastHost, toast } from "@/src/Toast";
import { MetricRow, Badge } from "@/src/parts";
import { useTTS } from "@/src/voice";
import { colors, spacing, radius } from "@/src/theme";

type Mode = "day" | "swing" | "long";

export default function StocksScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string }>();
  const [mode, setMode] = useState<Mode>(((params.mode as Mode) || "day"));
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    if (!ticker.trim()) { toast("Enter a ticker", "error"); return; }
    setLoading(true); setResult(null);
    try {
      const purpose = mode === "long" ? "long" : mode;
      const r = await api("/api/screener/stock-analysis", {
        method: "POST",
        body: JSON.stringify({ ticker: ticker.trim().toUpperCase(), purpose }),
      });
      setResult(r.result);
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  const modes: { id: Mode; label: string }[] = [
    { id: "day", label: "Day" },
    { id: "swing", label: "Swing" },
    { id: "long", label: "Long-term" },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.title}>Stock analysis</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.modeRow}>
          {modes.map((m) => {
            const active = mode === m.id;
            return (
              <Pressable
                key={m.id}
                testID={`stocks-mode-${m.id}`}
                onPress={() => { setMode(m.id); setResult(null); }}
                style={[styles.modeChip, active && styles.modeChipActive]}
              >
                <Text style={[styles.modeChipText, active && styles.modeChipTextActive]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.filterCard}>
          <Input testID="stocks-ticker" label="Ticker" value={ticker} onChangeText={(v) => setTicker(v.toUpperCase())} placeholder="e.g., TSLA" autoCapitalize="characters" />
          <Button testID="stocks-run" label={loading ? "Analyzing…" : "Analyze"} onPress={run} loading={loading} />
        </View>

        {loading && (
          <View style={{ padding: spacing.xl, alignItems: "center" }}>
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        )}

        {result && mode !== "long" && <ShortTermCard r={result} onTicker={() => router.push(`/ticker/${result.ticker}` as any)} />}
        {result && mode === "long" && <LongTermCard r={result} onTicker={() => router.push(`/ticker/${result.ticker}` as any)} />}
      </ScrollView>
      <ToastHost />
    </View>
  );
}

function VerdictBadge({ verdict, confidence }: { verdict: string; confidence?: string }) {
  const kind = verdict === "BUY" ? "success" : verdict === "SELL" ? "error" : "warn";
  return (
    <View style={{ flexDirection: "row", gap: 6 }}>
      <Badge text={verdict} kind={kind as any} />
      {confidence ? <Badge text={`${confidence} conf.`} kind="info" /> : null}
    </View>
  );
}

function ShortTermCard({ r, onTicker }: { r: any; onTicker: () => void }) {
  return (
    <View style={styles.resultCard}>
      <Pressable onPress={onTicker} style={styles.resultTop}>
        <View>
          <Text style={styles.ticker}>{r.ticker}</Text>
          <Text style={styles.company}>{r.name}</Text>
        </View>
        <Text style={styles.price}>${Number(r.price).toFixed(2)}</Text>
      </Pressable>
      <View style={{ marginTop: spacing.md, marginBottom: spacing.md }}>
        <VerdictBadge verdict={r.verdict} confidence={r.confidence} />
      </View>

      {r.ai_summary ? <SpeakableAi text={r.ai_summary} /> : null}

      <View style={styles.metricsGrid}>
        <KV label="Buy point" value={`$${r.buy_point}`} color={colors.success} />
        <KV label="Sell point" value={`$${r.sell_point}`} color={colors.brandPrimary} />
        <KV label="Stop loss" value={`$${r.stop_loss}`} color={colors.error} />
        <KV label="Support" value={`$${r.support}`} />
        <KV label="Resistance" value={`$${r.resistance}`} />
        <KV label="SMA 20" value={`$${r.sma_20}`} />
        <KV label="SMA 50" value={`$${r.sma_50}`} />
        <KV label="RSI" value={`${r.rsi}`} />
        <KV label="Short float" value={`${r.short_float_pct}%`} />
        <KV label="Opt. vol" value={`${(r.option_volume / 1000).toFixed(0)}k`} />
        <KV label="Sentiment" value={r.market_sentiment} />
        <KV label="Intrinsic" value={`$${r.intrinsic_value}`} />
        <KV label="Profit prob." value={`${r.profit_probability}%`} color={colors.success} />
      </View>

      <Text style={styles.sectionLabel}>Patterns</Text>
      <View style={styles.chipsRow}>
        {(r.candlestick_patterns || []).map((p: string) => <Badge key={p} text={p} kind="brand" />)}
        {(r.chart_patterns || []).map((p: string) => <Badge key={p} text={p} kind="success" />)}
      </View>
    </View>
  );
}

function LongTermCard({ r, onTicker }: { r: any; onTicker: () => void }) {
  return (
    <View style={styles.resultCard}>
      <Pressable onPress={onTicker} style={styles.resultTop}>
        <View>
          <Text style={styles.ticker}>{r.ticker}</Text>
          <Text style={styles.company}>{r.name}</Text>
        </View>
        <Text style={styles.price}>${Number(r.price).toFixed(2)}</Text>
      </Pressable>
      <View style={{ marginTop: spacing.md, marginBottom: spacing.md }}>
        <VerdictBadge verdict={r.verdict} confidence={r.confidence} />
      </View>

      {r.ai_summary ? <SpeakableAi text={r.ai_summary} /> : null}

      <Text style={styles.sectionLabel}>Valuation</Text>
      <MetricRow label="Intrinsic value" value={`$${r.intrinsic_value}`} />
      <MetricRow label="Price target" value={`$${r.price_target}`} color={colors.success} />
      <MetricRow label="Buy point" value={`$${r.buy_point}`} color={colors.success} />
      <MetricRow label="Sell point" value={`$${r.sell_point}`} color={colors.brandPrimary} />
      <MetricRow label="Trend" value={r.stock_trend} />

      <Text style={styles.sectionLabel}>Earnings</Text>
      <MetricRow label="Next date" value={r.earnings_date} />
      <MetricRow label="EPS estimate" value={`$${r.earnings_eps_estimate}`} />

      <Text style={styles.sectionLabel}>Financials ($B)</Text>
      <MetricRow label="Revenue" value={`$${r.revenue_billions}`} />
      <MetricRow label="Net profit" value={`$${r.net_profit_billions}`} color={r.net_profit_billions >= 0 ? colors.success : colors.error} />
      <MetricRow label="Net cash" value={`$${r.net_cash_billions}`} />
      <MetricRow label="Debt" value={`$${r.debt_billions}`} />

      <Text style={styles.sectionLabel}>Business</Text>
      <MetricRow label="Moat" value={r.business_moat} />
      {r.moat_note ? <Text style={styles.ai}>{r.moat_note}</Text> : null}

      <Text style={styles.sectionLabel}>Competitors</Text>
      <View style={styles.chipsRow}>{(r.competitors || []).map((c: string) => <Badge key={c} text={c} kind="brand" />)}</View>

      <Text style={styles.sectionLabel}>Analyst ratings</Text>
      <View style={styles.ratings}>
        <View style={[styles.ratingBar, { flex: r.analyst_ratings?.buy || 1, backgroundColor: colors.success }]}>
          <Text style={styles.ratingText}>Buy {r.analyst_ratings?.buy}</Text>
        </View>
        <View style={[styles.ratingBar, { flex: r.analyst_ratings?.hold || 1, backgroundColor: colors.warning }]}>
          <Text style={styles.ratingText}>Hold {r.analyst_ratings?.hold}</Text>
        </View>
        <View style={[styles.ratingBar, { flex: r.analyst_ratings?.sell || 1, backgroundColor: colors.error }]}>
          <Text style={styles.ratingText}>Sell {r.analyst_ratings?.sell}</Text>
        </View>
      </View>
    </View>
  );
}

function KV({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <View style={styles.metricBox}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricVal, color ? { color } : null]}>{value}</Text>
    </View>
  );
}

function SpeakableAi({ text }: { text: string }) {
  const { play, stop, loading, playing } = useTTS();
  return (
    <View style={styles.aiRow}>
      <Text style={styles.aiText}>{text}</Text>
      <Pressable testID="stock-speak-btn" onPress={() => (playing ? stop() : play(text))} style={styles.speakBtn}>
        <Icon name={loading ? "loader" : playing ? "pause" : "volume-2"} size={16} color={colors.brandPrimary} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider },
  title: { fontSize: 22, fontWeight: "800", color: colors.onSurface },
  modeRow: { gap: spacing.sm, paddingTop: spacing.md, paddingRight: spacing.lg },
  modeChip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", flexShrink: 0, borderWidth: 1, borderColor: colors.border },
  modeChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  modeChipText: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  modeChipTextActive: { color: colors.onBrandPrimary },
  scroll: { padding: spacing.lg, paddingBottom: 100 },
  filterCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg },

  resultCard: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md },
  resultTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  ticker: { fontSize: 22, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  company: { fontSize: 12, color: colors.muted },
  price: { fontSize: 18, fontWeight: "800", color: colors.onSurface, fontVariant: ["tabular-nums"] },

  ai: { backgroundColor: colors.brandSecondary, padding: spacing.md, borderRadius: radius.md, color: colors.onBrandSecondary, fontSize: 13, lineHeight: 18, marginBottom: spacing.md },
  aiRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start", backgroundColor: colors.brandSecondary, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md },
  aiText: { flex: 1, color: colors.onBrandSecondary, fontSize: 13, lineHeight: 18 },
  speakBtn: { width: 32, height: 32, borderRadius: radius.pill, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },

  metricsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  metricBox: { flexGrow: 1, flexBasis: "30%", backgroundColor: colors.surfaceSecondary, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  metricLabel: { fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  metricVal: { fontSize: 14, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"] },
  sectionLabel: { fontSize: 12, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1, marginTop: spacing.lg, marginBottom: spacing.sm },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },

  ratings: { flexDirection: "row", height: 32, borderRadius: radius.md, overflow: "hidden", gap: 2 },
  ratingBar: { alignItems: "center", justifyContent: "center" },
  ratingText: { color: "#FFFFFF", fontWeight: "700", fontSize: 11 },
});
