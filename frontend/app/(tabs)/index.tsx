import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
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
import { Filters, ProfileId, PROFILE_INFO, defaultFilters, filtersPayload, FilterPanel, ProfilePicker, Label, accountLabel } from "@/src/screen";

type Mode = "find" | "best";
const EXPIRATION = ["daily", "week", "month", "3months"];
const SECTORS = ["Tech", "Consumer Discretionary", "Financials", "Energy", "Healthcare", "Consumer Staples", "Industrials", "Index"];
const PERIODS = ["day", "week", "month", "custom"];
const REJECT_LABEL: Record<string, string> = { max_loss: "max loss", pop: "probability", roc: "return", liquidity: "liquidity", iv_rank: "IV rank", earnings: "earnings", undefined_risk: "undefined risk", account_type: "account type", options_level: "options level", capital: "capital needed" };

export default function Discover() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();
  const [mode, setMode] = useState<Mode>("best");
  const [f, setF] = useState<Filters>(defaultFilters("low_low"));
  const set = (p: Partial<Filters>) => setF((c) => ({ ...c, ...p }));
  const [exp, setExp] = useState("week");
  const [sectors, setSectors] = useState<string[]>([]);
  const [period, setPeriod] = useState("week");
  const [customDays, setCustomDays] = useState("14");
  const [limit, setLimit] = useState("5");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [summary, setSummary] = useState("");
  const [aiMap, setAiMap] = useState<Record<string, any>>({});
  const [aiLoading, setAiLoading] = useState(false);
  const [locked, setLocked] = useState<Record<string, boolean>>({});
  const [levelLabel, setLevelLabel] = useState("");

  useEffect(() => {
    api("/api/screener/profiles").then((r) => {
      if (r?.defaults) set({ account_type: r.defaults.account_type, account_size: String(r.defaults.account_size) });
      const lk: Record<string, boolean> = {};
      Object.entries(r?.profiles || {}).forEach(([k, v]: any) => { lk[k] = !!v.locked; });
      setLocked(lk);
      setLevelLabel(r?.options_level_label || "");
    }).catch(() => {});
  }, []);

  const toggleSector = (s: string) => setSectors((c) => c.includes(s) ? c.filter((x) => x !== s) : [...c, s]);
  const pickProfile = (p: ProfileId) => set({ profile: p, ...PROFILE_INFO[p].defaults });

  const explain = async (rows: any[], context: string) => {
    if (!rows.length) return;
    setAiLoading(true);
    try {
      const ideas = rows.map((r) => ({ ticker: r.ticker, strategy: r.strategy, price: r.price, pop: r.pop, roc_pct: r.roc_pct,
        max_profit: r.max_profit, max_loss: r.max_loss, iv_rank: r.volatility?.iv_rank, liquidity: r.liquidity?.grade,
        earnings_in_window: r.events?.earnings_in_window, dte: r.expiration_days }));
      const a = await api("/api/screener/explain", { method: "POST", body: JSON.stringify({ ideas, context }) });
      setSummary(a.summary || "");
      const m: Record<string, any> = {};
      (a.picks || []).forEach((p: any) => { m[p.ticker] = p; });
      setAiMap(m);
    } catch {} finally { setAiLoading(false); }
  };

  const run = async () => {
    setLoading(true); setResults([]); setSummary(""); setAiMap({}); setStats(null);
    try {
      const base = { ...filtersPayload(f), limit: parseInt(limit) || 5 };
      const r = mode === "find"
        ? await api("/api/screener/find-stocks", { method: "POST", body: JSON.stringify({ ...base, expiration: exp, sectors }) })
        : await api("/api/screener/best-options", { method: "POST", body: JSON.stringify({ ...base, period, custom_days: period === "custom" ? parseInt(customDays) : null }) });
      setResults(r.results || []); setStats(r.stats);
      explain(r.results || [], `${PROFILE_INFO[f.profile].title}, ${mode === "find" ? exp : period} horizon, ${accountLabel(f.account_type)} account`);
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
              <Pressable key={m.id} testID={`disc-mode-${m.id}`} onPress={() => { setMode(m.id as Mode); setResults([]); setSummary(""); setStats(null); }} style={[styles.modeChip, active && styles.modeChipActive]}>
                <Text style={[styles.modeChipText, active && styles.modeChipTextActive]}>{m.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.filterCard}>
          <Pressable testID="open-track-record" onPress={() => router.push("/track-record" as any)} style={styles.trackLink}>
            <Icon name="check-square" size={16} color={colors.brandPrimary} />
            <Text style={styles.trackText}>Track record: did 70%+ picks really win?</Text>
            <Icon name="chevron-right" size={16} color={colors.brandPrimary} />
          </Pressable>
          <Label>Risk profile</Label>
          {levelLabel ? (
            <View testID="level-banner" style={styles.levelBanner}>
              <Icon name="award" size={14} color={colors.brandPrimary} />
              <Text style={styles.levelText}>Your options level: {levelLabel}</Text>
            </View>
          ) : null}
          <ProfilePicker value={f.profile} onChange={pickProfile} locked={locked} />
          {mode === "find" ? (
            <>
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
          <FilterPanel f={f} set={set} />
          <Input testID="limit-input" label="Number of ideas" value={limit} onChangeText={setLimit} keyboardType="numeric" />
          <Button testID="disc-run" label={loading ? "Scanning…" : "Scan markets"} onPress={run} loading={loading} />
          <Text style={styles.disclaimer}>The math engine prices every idea and applies your filters (risk, probability, liquidity, IV) before ranking. AI only explains. Research only — not investment advice.</Text>
        </View>

        {stats ? (
          <Text testID="scan-stats" style={styles.stats}>
            {stats.tickers_scanned} stocks · {stats.ideas_evaluated} setups priced · {stats.passed} passed
            {Object.keys(stats.rejected_by || {}).length ? ` · filtered by ${Object.entries(stats.rejected_by).sort((a: any, b: any) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${REJECT_LABEL[k] || k} (${v})`).join(", ")}` : ""}
          </Text>
        ) : null}
        {stats && !results.length && !loading ? (
          <View style={styles.empty}>
            <Icon name="filter" size={20} color={colors.muted} />
            <Text style={styles.emptyText}>No setups passed your filters. Loosen max loss, probability or liquidity under &quot;Fine-tune risk numbers&quot;.</Text>
          </View>
        ) : null}
        {aiLoading && !summary ? <Text style={styles.stats}>AI is writing explanations…</Text> : null}
        {summary ? (
          <View style={styles.ai}>
            <Icon name="zap" size={16} color={colors.brandPrimary} />
            <Text style={styles.aiText}>{summary}</Text>
          </View>
        ) : null}

        {loading && !results.length && <LoadingSkeleton lines={6} />}

        {results.map((r, i) => (
          <Pressable key={i} testID={`disc-result-${r.ticker}`} onPress={() => router.push({ pathname: "/(tabs)/analyze", params: { ticker: r.ticker, strategy: r.strategy, range: r.expiration_days > 45 ? "3months" : r.expiration_days > 10 ? "month" : "week" } } as any)} style={styles.resultCard}>
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
                <Text style={styles.aprMini}>ROC {r.roc_pct != null ? `${r.roc_pct}%` : "∞"}</Text>
              </View>
            </View>
            <View style={styles.metricsRow}>
              <Mini label="POP" value={`${r.pop}%`} />
              <Mini label={r.premium_type === "debit" ? "Debit" : "Credit"} value={`$${r.premium}`} />
              <Mini label="Max profit" value={r.max_profit != null ? `$${r.max_profit}` : "∞"} tone="success" />
              <Mini label="Max loss" value={r.max_loss != null ? `$${r.max_loss}` : "undef"} tone="error" />
            </View>
            <View style={styles.tagRow}>
              <Badge text={`Liquidity ${r.liquidity?.grade || "—"} (est.)`} kind={r.liquidity?.grade === "High" ? "success" : r.liquidity?.grade === "Low" ? "error" : "info"} />
              <Badge text={`IV rank ${Math.round(r.volatility?.iv_rank ?? 0)}`} kind="info" />
              <Badge text={`${r.expiration_days}d`} kind="info" />
              {r.events?.earnings_in_window ? <Badge text="Earnings in window" kind="warn" /> : null}
            </View>
            {aiMap[r.ticker]?.why ? <Text style={styles.rationale}>{aiMap[r.ticker].why}</Text> : <Text style={styles.rationale}>{r.why?.[0]}</Text>}
            {aiMap[r.ticker]?.risk ? <Text style={[styles.rationale, { color: colors.error }]}>Risk: {aiMap[r.ticker].risk}</Text> : null}
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

  trackLink: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 44, paddingHorizontal: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brandPrimary, marginBottom: spacing.md },
  trackText: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.brandPrimary },
  levelBanner: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.brandSecondary, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.md },
  levelText: { flex: 1, fontSize: 12, fontWeight: "700", color: colors.onBrandSecondary },
  stats: { fontSize: 11, color: colors.muted, marginBottom: spacing.sm, lineHeight: 16 },
  empty: { alignItems: "center", gap: spacing.sm, padding: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  emptyText: { color: colors.onSurfaceSecondary, fontSize: 13, textAlign: "center", lineHeight: 18 },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  rationale: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: spacing.sm, fontStyle: "italic", lineHeight: 17 },
});
