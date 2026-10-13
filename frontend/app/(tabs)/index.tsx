import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { Button } from "@/src/Button";
import { Input } from "@/src/Input";
import { ToastHost, toast } from "@/src/Toast";
import { Sparkline, Badge } from "@/src/parts";
import { LoadingSkeleton } from "@/src/charts";
import { colors, spacing, radius } from "@/src/theme";

type Mode = "find" | "best";
const RISK = ["low", "high"];
const REWARD = ["low", "high"];
const EXPIRATION = ["daily", "week", "month"];
const SECTORS = ["Tech", "Consumer Discretionary", "Financials", "Energy", "Healthcare", "Consumer Staples", "Industrials", "Index"];
const PERIODS = ["day", "week", "month", "custom"];

export default function Discover() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const [mode, setMode] = useState<Mode>("best");
  // Find
  const [risk, setRisk] = useState("high");
  const [reward, setReward] = useState("high");
  const [exp, setExp] = useState("week");
  const [sectors, setSectors] = useState<string[]>([]);
  // Best
  const [period, setPeriod] = useState("week");
  const [customDays, setCustomDays] = useState("14");
  const [limit, setLimit] = useState("5");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [summary, setSummary] = useState("");

  const toggleSector = (s: string) => setSectors((c) => c.includes(s) ? c.filter((x) => x !== s) : [...c, s]);

  const run = async () => {
    setLoading(true); setResults([]); setSummary("");
    try {
      if (mode === "find") {
        const r = await api("/api/screener/find-stocks", {
          method: "POST",
          body: JSON.stringify({ risk, reward, expiration: exp, sectors, limit: parseInt(limit) || 5 }),
        });
        setResults(r.results || []);
      } else {
        const r = await api("/api/screener/best-options", {
          method: "POST",
          body: JSON.stringify({ period, custom_days: period === "custom" ? parseInt(customDays) : null, limit: parseInt(limit) || 5 }),
        });
        setResults(r.results || []); setSummary(r.ai_summary || "");
      }
    } catch (e: any) { toast(e.message || "Failed", "error"); }
    finally { setLoading(false); }
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <View style={styles.headerTop}>
          <View>
            <Text style={styles.hello}>Hi, {user?.name?.split(" ")[0] || "trader"}</Text>
            <Text style={styles.title}>Discover</Text>
          </View>
          <Pressable testID="go-profile" onPress={() => router.push("/profile" as any)} style={styles.avatar}>
            <Text style={styles.avatarText}>{(user?.name || user?.email || "?").slice(0, 1).toUpperCase()}</Text>
          </Pressable>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.modeRow}>
          {[{ id: "best", label: "Best opportunities" }, { id: "find", label: "Find stocks" }].map((m) => {
            const active = mode === m.id;
            return (
              <Pressable key={m.id} testID={`disc-mode-${m.id}`} onPress={() => { setMode(m.id as Mode); setResults([]); setSummary(""); }} style={[styles.modeChip, active && styles.modeChipActive]}>
                <Text style={[styles.modeChipText, active && styles.modeChipTextActive]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.filterCard}>
          {mode === "find" ? (
            <>
              <ChipRow label="Risk tolerance" value={risk} onChange={setRisk} options={RISK} testKey="risk" />
              <ChipRow label="Reward target" value={reward} onChange={setReward} options={REWARD} testKey="reward" />
              <ChipRow label="Expiration" value={exp} onChange={setExp} options={EXPIRATION} testKey="exp" />
              <Text style={styles.chipLabel}>Sectors</Text>
              <View style={styles.chipsWrap}>
                {SECTORS.map((s) => {
                  const active = sectors.includes(s);
                  return (
                    <Pressable key={s} testID={`sector-${s}`} onPress={() => toggleSector(s)} style={[styles.chip, active && styles.chipActive]}>
                      <Text style={[styles.chipText, active && styles.chipTextActive]}>{s}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </>
          ) : (
            <>
              <ChipRow label="Period" value={period} onChange={setPeriod} options={PERIODS} testKey="period" />
              {period === "custom" ? <Input testID="custom-days" label="Custom days" value={customDays} onChangeText={setCustomDays} keyboardType="numeric" /> : null}
            </>
          )}
          <Input testID="limit-input" label="Number of ideas" value={limit} onChangeText={setLimit} keyboardType="numeric" />
          <Button testID="disc-run" label={loading ? "Scanning…" : "Scan markets"} onPress={run} loading={loading} />
          <Text style={styles.disclaimer}>Hard filters (liquidity, data freshness) are applied before ranking. Research only — not investment advice.</Text>
        </View>

        {summary ? (
          <View style={styles.ai}>
            <Icon name="zap" size={16} color={colors.brandPrimary} />
            <Text style={styles.aiText}>{summary}</Text>
          </View>
        ) : null}

        {loading && !results.length && <LoadingSkeleton lines={6} />}

        {results.map((r, i) => (
          <Pressable key={i} testID={`disc-result-${r.ticker}`} onPress={() => router.push(`/ticker/${r.ticker}` as any)} style={styles.resultCard}>
            <View style={styles.strategyStripe} />
            <View style={styles.resultTop}>
              <View style={{ flex: 1 }}>
                <Text style={styles.ticker}>{r.ticker}</Text>
                <Text style={styles.company} numberOfLines={1}>{r.name}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
                  <Badge text={r.strategy} kind="brand" />
                  {r.bias ? <Badge text={r.bias} kind={r.bias === "bullish" ? "success" : r.bias === "bearish" ? "error" : "info"} /> : null}
                </View>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={styles.price}>${Number(r.price).toFixed(2)}</Text>
                <Sparkline data={r.sparkline || []} up={(r.annual_pct_no_margin || 0) >= 0} />
                <Text style={styles.aprMini}>APR {r.annual_pct_no_margin}%</Text>
              </View>
            </View>
            <View style={styles.metricsRow}>
              <Mini label="POP" value={`${r.pop}%`} />
              <Mini label="Premium" value={`$${r.premium}`} />
              <Mini label="Max profit" value={r.max_profit != null ? `$${r.max_profit}` : "—"} tone="success" />
              <Mini label="Max loss" value={r.max_loss != null ? `$${r.max_loss}` : "undef"} tone="error" />
            </View>
            {r.rationale ? <Text style={styles.rationale}>{r.rationale}</Text> : null}
          </Pressable>
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
      <View style={styles.chipsWrap}>
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

function Mini({ label, value, tone }: { label: string; value: string; tone?: "success" | "error" }) {
  const color = tone === "success" ? colors.success : tone === "error" ? colors.error : colors.onSurface;
  return (
    <View style={styles.mini}>
      <Text style={styles.miniLabel}>{label}</Text>
      <Text style={[styles.miniVal, { color }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider },
  headerTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  hello: { fontSize: 11, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, fontWeight: "700" },
  title: { fontSize: 26, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  avatarText: { color: colors.onBrandPrimary, fontWeight: "800" },
  modeRow: { gap: spacing.sm, paddingTop: spacing.md, paddingRight: spacing.lg },
  modeChip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", flexShrink: 0, borderWidth: 1, borderColor: colors.border },
  modeChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  modeChipText: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  modeChipTextActive: { color: colors.onBrandPrimary },

  scroll: { padding: spacing.lg, paddingBottom: 100 },
  filterCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.lg },
  chipLabel: { fontSize: 12, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginBottom: spacing.md },
  chip: { paddingHorizontal: spacing.md, height: 32, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipText: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  chipTextActive: { color: colors.onBrandPrimary },
  disclaimer: { color: colors.muted, fontSize: 11, marginTop: spacing.sm, fontStyle: "italic" },

  ai: { flexDirection: "row", gap: spacing.sm, backgroundColor: colors.brandSecondary, padding: spacing.md, borderRadius: radius.md, marginBottom: spacing.md, alignItems: "flex-start" },
  aiText: { flex: 1, color: colors.onBrandSecondary, fontSize: 13, lineHeight: 18, fontWeight: "500" },

  resultCard: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginBottom: spacing.md, overflow: "hidden" },
  strategyStripe: { position: "absolute", left: 0, top: 0, bottom: 0, width: 4, backgroundColor: colors.brandPrimary },
  resultTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  ticker: { fontSize: 22, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  company: { fontSize: 12, color: colors.muted, marginTop: 2 },
  price: { fontSize: 16, fontWeight: "800", color: colors.onSurface, fontVariant: ["tabular-nums"], marginBottom: 4 },
  aprMini: { fontSize: 10, fontWeight: "700", color: colors.success, marginTop: 4, fontVariant: ["tabular-nums"] },

  metricsRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md },
  mini: { flexGrow: 1, flexBasis: "18%", backgroundColor: colors.surfaceSecondary, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  miniLabel: { fontSize: 9, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  miniVal: { fontSize: 13, fontWeight: "700", fontVariant: ["tabular-nums"], marginTop: 2 },

  rationale: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.sm, fontStyle: "italic", lineHeight: 17 },
});
