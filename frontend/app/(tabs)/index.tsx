import React from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { useAuth } from "@/src/auth";
import { colors, spacing, radius } from "@/src/theme";

const SHORTCUTS = [
  { title: "Find Stocks", desc: "Risk/reward filter", icon: "filter", href: "/options?mode=find" },
  { title: "Best Options", desc: "Top strategies now", icon: "layers", href: "/options?mode=best" },
  { title: "Ticker Options", desc: "Analyze one stock", icon: "search", href: "/options?mode=ticker" },
  { title: "Day / Swing", desc: "Short-term plays", icon: "activity", href: "/stocks?mode=day" },
  { title: "Long-term", desc: "Fundamentals", icon: "bar-chart-2", href: "/stocks?mode=long" },
];

export default function Home() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user } = useAuth();

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <ScrollView contentContainerStyle={[styles.scroll, { paddingTop: insets.top + spacing.md }]}>
        <View style={styles.header}>
          <View>
            <Text style={styles.hello}>Hi, {user?.name?.split(" ")[0] || "trader"}</Text>
            <Text style={styles.title}>What are we trading today?</Text>
          </View>
          <View style={styles.planBadge}>
            <Icon name="award" size={12} color={colors.onBrandSecondary} />
            <Text style={styles.planBadgeText}>{(user?.plan || "free").toUpperCase()}</Text>
          </View>
        </View>

        <Text style={styles.section}>Quick actions</Text>
        <View style={styles.grid}>
          {SHORTCUTS.map((s) => (
            <Pressable
              key={s.title}
              testID={`home-${s.title.replace(/\s+/g, "-").toLowerCase()}`}
              onPress={() => router.push(s.href as any)}
              style={styles.card}
            >
              <View style={styles.cardIcon}>
                <Icon name={s.icon as any} size={20} color={colors.brandPrimary} />
              </View>
              <Text style={styles.cardTitle}>{s.title}</Text>
              <Text style={styles.cardDesc}>{s.desc}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.section}>Pro tip</Text>
        <View style={styles.tip}>
          <Icon name="zap" size={18} color={colors.warning} />
          <Text style={styles.tipText}>
            AI picks premium-rich plays with 70%+ probability of profit. Combine with your own thesis before entering.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.xl },
  hello: { fontSize: 12, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, fontWeight: "700" },
  title: { fontSize: 24, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  planBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandSecondary, paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill,
  },
  planBadgeText: { color: colors.onBrandSecondary, fontWeight: "700", fontSize: 11, marginLeft: 4 },
  section: { fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.md },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginBottom: spacing.xl },
  card: {
    width: "48%", backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
  },
  cardIcon: {
    width: 36, height: 36, borderRadius: radius.md, backgroundColor: colors.brandSecondary,
    alignItems: "center", justifyContent: "center", marginBottom: spacing.sm,
  },
  cardTitle: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  cardDesc: { fontSize: 12, color: colors.muted, marginTop: 2 },
  tip: {
    flexDirection: "row", gap: spacing.md, backgroundColor: colors.surfaceSecondary,
    padding: spacing.lg, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, alignItems: "flex-start",
  },
  tipText: { flex: 1, fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 19 },
});
