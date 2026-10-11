import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { Input } from "@/src/Input";
import { ToastHost, toast } from "@/src/Toast";
import { Sparkline, MetricRow, Badge } from "@/src/parts";
import { useTTS, useSTT } from "@/src/voice";
import { colors, spacing, radius } from "@/src/theme";

type Mode = "find" | "best" | "ticker";

const RISK = ["low", "high"];
const REWARD = ["low", "high"];
const EXPIRATION = ["daily", "week", "month"];
const SECTORS = ["Tech", "Consumer Discretionary", "Financials", "Energy", "Healthcare", "Consumer Staples", "Industrials", "Index"];
const PERIODS = ["day", "week", "month", "custom"];
const EXP_RANGES = ["week", "month", "3months"];

export default function OptionsScreen() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string }>();
  const [mode, setMode] = useState<Mode>(((params.mode as Mode) || "find"));

  // Find Stocks state
  const [risk, setRisk] = useState("high");
  const [reward, setReward] = useState("high");
  const [exp, setExp] = useState("week");
  const [sectors, setSectors] = useState<string[]>([]);
  // Best Options state
  const [period, setPeriod] = useState("week");
  const [customDays, setCustomDays] = useState("14");
  // Ticker state
  const [ticker, setTicker] = useState("");
  const [range, setRange] = useState("month");
  // Common
  const [limit, setLimit] = useState("5");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [aiSummary, setAiSummary] = useState<string>("");

  const toggleSector = (s: string) => setSectors((cur) => cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]);

  const run = async () => {
    setLoading(true); setResults([]); setAiSummary("");
    try {
      if (mode === "find") {
        const r = await api("/api/screener/find-stocks", {
          method: "POST",
          body: JSON.stringify({ risk, reward, expiration: exp, sectors, limit: parseInt(limit) || 5 }),
        });
        setResults(r.results || []);
      } else if (mode === "best") {
        const r = await api("/api/screener/best-options", {
          method: "POST",
          body: JSON.stringify({ period, custom_days: period === "custom" ? parseInt(customDays) : null, limit: parseInt(limit) || 5 }),
        });
        setResults(r.results || []);
        setAiSummary(r.ai_summary || "");
      } else {
        if (!ticker.trim()) { toast("Enter a ticker", "error"); setLoading(false); return; }
        const r = await api("/api/screener/ticker-options", {
          method: "POST",
          body: JSON.stringify({ ticker: ticker.trim().toUpperCase(), expiration_range: range }),
        });
        setResults([r.result]);
        setAiSummary(r.result.ai_summary || "");
      }
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  const modes: { id: Mode; label: string }[] = [
    { id: "find", label: "Find Stocks" },
    { id: "best", label: "Best Options" },
    { id: "ticker", label: "Ticker" },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.title}>Options screener</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.modeRow}>
          {modes.map((m) => {
            const active = mode === m.id;
            return (
              <Pressable
                key={m.id}
                testID={`options-mode-${m.id}`}
                onPress={() => { setMode(m.id); setResults([]); setAiSummary(""); }}
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
          {mode === "find" && (
            <>
              <ChipRow label="Risk" value={risk} onChange={setRisk} options={RISK} testKey="risk" />
              <ChipRow label="Reward" value={reward} onChange={setReward} options={REWARD} testKey="reward" />
              <ChipRow label="Expiration" value={exp} onChange={setExp} options={EXPIRATION} testKey="exp" />
              <Text style={styles.chipLabel}>Sectors</Text>
              <View style={styles.chipsRow}>
                {SECTORS.map((s) => {
                  const active = sectors.includes(s);
                  return (
                    <Pressable key={s} testID={`sector-${s}`} onPress={() => toggleSector(s)} style={[styles.chip, active && styles.chipActive]}>
                      <Text style={[styles.chipText, active && styles.chipTextActive]}>{s}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <LimitInput value={limit} onChange={setLimit} />
            </>
          )}

          {mode === "best" && (
            <>
              <ChipRow label="Period" value={period} onChange={setPeriod} options={PERIODS} testKey="period" />
              {period === "custom" && (
                <Input testID="custom-days" label="Custom days" value={customDays} onChangeText={setCustomDays} keyboardType="numeric" />
              )}
              <LimitInput value={limit} onChange={setLimit} />
            </>
          )}

          {mode === "ticker" && (
            <>
              <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "flex-end" }}>
                <View style={{ flex: 1 }}>
                  <Input testID="ticker-input" label="Ticker" value={ticker} onChangeText={(v) => setTicker(v.toUpperCase())} placeholder="e.g., AAPL" autoCapitalize="characters" />
                </View>
                <MicButton onText={(t) => {
                  const m = t.toUpperCase().match(/[A-Z]{1,5}/);
                  if (m) setTicker(m[0]);
                }} />
              </View>
              <ChipRow label="Expiration range" value={range} onChange={setRange} options={EXP_RANGES} testKey="range" />
            </>
          )}

          <Button testID="options-run" label={loading ? "Analyzing…" : "Run screener"} onPress={run} loading={loading} />
        </View>

        {aiSummary ? (
          <View style={styles.ai}>
            <Icon name="zap" size={16} color={colors.brandPrimary} />
            <Text style={styles.aiText}>{aiSummary}</Text>
            <SpeakButton text={aiSummary} />
          </View>
        ) : null}

        {loading && !results.length && (
          <View style={{ padding: spacing.xl, alignItems: "center" }}>
            <ActivityIndicator color={colors.brandPrimary} />
          </View>
        )}

        {results.map((r, i) => (
          <OptionResultCard key={i} r={r} onTicker={() => router.push(`/ticker/${r.ticker}` as any)} />
        ))}
      </ScrollView>
      <ToastHost />
    </View>
  );
}

function ChipRow({ label, value, onChange, options, testKey }: { label: string; value: string; onChange: (v: string) => void; options: string[]; testKey: string }) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={styles.chipLabel}>{label}</Text>
      <View style={styles.chipsRow}>
        {options.map((o) => {
          const active = value === o;
          return (
            <Pressable key={o} testID={`${testKey}-${o}`} onPress={() => onChange(o)} style={[styles.chip, active && styles.chipActive]}>
              <Text style={[styles.chipText, active && styles.chipTextActive]}>{o}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

function LimitInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <Input testID="limit-input" label="How many results" value={value} onChangeText={onChange} keyboardType="numeric" />;
}

function SpeakButton({ text }: { text: string }) {
  const { play, stop, loading, playing } = useTTS();
  return (
    <Pressable
      testID="speak-btn"
      onPress={() => (playing ? stop() : play(text))}
      style={styles.speakBtn}
    >
      <Icon name={loading ? "loader" : playing ? "pause" : "volume-2"} size={16} color={colors.brandPrimary} />
    </Pressable>
  );
}

function MicButton({ onText }: { onText: (t: string) => void }) {
  const { start, stop, recording, loading } = useSTT(onText);
  return (
    <Pressable
      testID="mic-btn"
      onPress={() => (recording ? stop() : start())}
      style={[styles.micBtn, recording && styles.micBtnActive]}
    >
      <Icon name={loading ? "loader" : recording ? "square" : "mic"} size={18} color={recording ? colors.onError : colors.brandPrimary} />
    </Pressable>
  );
}

function OptionResultCard({ r, onTicker }: { r: any; onTicker: () => void }) {
  const [open, setOpen] = useState(false);
  const up = r.bias ? r.bias === "bullish" : (r.annual_pct_no_margin || 0) >= 0;
  return (
    <View style={styles.resultCard}>
      <View style={styles.resultTop}>
        <Pressable onPress={onTicker} testID={`result-ticker-${r.ticker}`}>
          <Text style={styles.ticker}>{r.ticker}</Text>
          <Text style={styles.company} numberOfLines={1}>{r.name}</Text>
        </Pressable>
        <View style={{ alignItems: "flex-end" }}>
          <Text style={styles.price}>${Number(r.price).toFixed(2)}</Text>
          <Sparkline data={r.sparkline || []} up={up} />
        </View>
      </View>
      <View style={styles.resultStrategyRow}>
        <Badge text={r.strategy} kind="brand" />
        {r.bias ? <Badge text={r.bias} kind={r.bias === "bullish" ? "success" : r.bias === "bearish" ? "error" : "info"} /> : null}
      </View>

      <View style={styles.metricsGrid}>
        <View style={styles.metricBox}>
          <Text style={styles.metricLabel}>Pop</Text>
          <Text style={styles.metricVal}>{r.pop}%</Text>
        </View>
        <View style={styles.metricBox}>
          <Text style={styles.metricLabel}>Premium</Text>
          <Text style={styles.metricVal}>${r.premium}</Text>
        </View>
        <View style={styles.metricBox}>
          <Text style={styles.metricLabel}>Exp</Text>
          <Text style={styles.metricVal}>{r.expiration}</Text>
        </View>
        <View style={styles.metricBox}>
          <Text style={styles.metricLabel}>APR (collat)</Text>
          <Text style={[styles.metricVal, { color: colors.success }]}>{r.annual_pct_no_margin}%</Text>
        </View>
      </View>

      <Pressable testID={`result-expand-${r.ticker}`} onPress={() => setOpen((x) => !x)} style={styles.expandRow}>
        <Text style={styles.expandText}>{open ? "Hide" : "Show"} legs & details</Text>
        <Icon name={open ? "chevron-up" : "chevron-down"} size={16} color={colors.brandPrimary} />
      </Pressable>

      {open && (
        <View style={styles.details}>
          {r.rationale ? <Text style={styles.rationale}>{r.rationale}</Text> : null}
          {(r.legs || []).map((l: any, i: number) => (
            <MetricRow key={i} label={`${l.action} ${l.type}`} value={`$${l.strike} • ${l.exp}`} />
          ))}
          <MetricRow label="Collateral" value={`$${r.collateral}`} />
          <MetricRow label="w/ Margin" value={`$${r.collateral_margin}`} />
          <MetricRow label="APR (margin)" value={`${r.annual_pct_margin}%`} color={colors.success} />
          {r.risk_note ? <Text style={styles.rationale}>Risk: {r.risk_note}</Text> : null}
          {r.entry_tip ? <Text style={styles.rationale}>Tip: {r.entry_tip}</Text> : null}
        </View>
      )}
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
  chipLabel: { fontSize: 13, color: colors.muted, fontWeight: "600", textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  chip: { paddingHorizontal: spacing.md, height: 32, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  chipTextActive: { color: colors.onBrandPrimary },

  ai: { flexDirection: "row", gap: spacing.sm, backgroundColor: colors.brandSecondary, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md, alignItems: "flex-start" },
  aiText: { flex: 1, color: colors.onBrandSecondary, fontSize: 13, lineHeight: 18, fontWeight: "500" },
  speakBtn: { width: 32, height: 32, borderRadius: radius.pill, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" },
  micBtn: { width: 48, height: 48, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.lg, borderWidth: 1, borderColor: colors.border },
  micBtnActive: { backgroundColor: colors.error, borderColor: colors.error },

  resultCard: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md },
  resultTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  ticker: { fontSize: 20, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  company: { fontSize: 12, color: colors.muted, maxWidth: 160 },
  price: { fontSize: 16, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"], marginBottom: 4 },
  resultStrategyRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm, marginBottom: spacing.md },

  metricsGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  metricBox: { flexGrow: 1, flexBasis: "22%", backgroundColor: colors.surfaceSecondary, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  metricLabel: { fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 },
  metricVal: { fontSize: 14, fontWeight: "700", color: colors.onSurface, fontVariant: ["tabular-nums"] },

  expandRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.md, paddingVertical: spacing.sm },
  expandText: { color: colors.brandPrimary, fontWeight: "700", fontSize: 13 },
  details: { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  rationale: { fontSize: 13, color: colors.onSurfaceSecondary, marginVertical: 4, fontStyle: "italic" },
});
