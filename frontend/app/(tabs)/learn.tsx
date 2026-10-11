import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Icon from "@react-native-vector-icons/feather";

import { api } from "@/src/api";
import { Badge } from "@/src/parts";
import { useTTS } from "@/src/voice";
import { colors, spacing, radius } from "@/src/theme";

export default function Learn() {
  const insets = useSafeAreaInsets();
  const [cards, setCards] = useState<any[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("All");
  const { play, stop, playing } = useTTS();

  useEffect(() => {
    api("/api/learn/cards").then((r) => setCards(r.cards || [])).catch(() => {});
  }, []);

  const categories = ["All", ...Array.from(new Set(cards.map((c) => c.category)))];
  const visible = filter === "All" ? cards : cards.filter((c) => c.category === filter);

  return (
    <View style={{ flex: 1, backgroundColor: colors.surface }}>
      <View style={[styles.header, { paddingTop: insets.top + spacing.md }]}>
        <Text style={styles.title}>Learn</Text>
        <Text style={styles.sub}>Strategy playbook & risk primer</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.modeRow}>
          {categories.map((c) => {
            const active = filter === c;
            return (
              <Pressable key={c} testID={`cat-${c}`} onPress={() => setFilter(c)} style={[styles.modeChip, active && styles.modeChipActive]}>
                <Text style={[styles.modeChipText, active && styles.modeChipTextActive]}>{c}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {visible.map((c) => {
          const expanded = open === c.id;
          return (
            <Pressable key={c.id} testID={`learn-${c.id}`} onPress={() => setOpen(expanded ? null : c.id)} style={styles.card}>
              <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
                <View style={{ flex: 1 }}>
                  <Badge text={c.category} kind="brand" />
                  <Text style={styles.cardTitle}>{c.title}</Text>
                  {c.outlook ? <Text style={styles.outlook}>Outlook: {c.outlook}</Text> : null}
                </View>
                <Icon name={expanded ? "chevron-up" : "chevron-down"} size={18} color={colors.muted} />
              </View>
              <Text style={styles.summary}>{c.summary}</Text>
              {expanded && (
                <View style={styles.expanded}>
                  {c.pros?.length ? (
                    <>
                      <Text style={styles.sectionLabel}>Pros</Text>
                      {c.pros.map((p: string) => <Row key={p} icon="check" color={colors.success} text={p} />)}
                    </>
                  ) : null}
                  {c.cons?.length ? (
                    <>
                      <Text style={styles.sectionLabel}>Cons</Text>
                      {c.cons.map((p: string) => <Row key={p} icon="x" color={colors.error} text={p} />)}
                    </>
                  ) : null}
                  {c.when ? (
                    <>
                      <Text style={styles.sectionLabel}>When to use</Text>
                      <Text style={styles.when}>{c.when}</Text>
                    </>
                  ) : null}
                  <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.md }}>
                    <Pressable
                      testID={`learn-speak-${c.id}`}
                      onPress={() => (playing ? stop() : play(`${c.title}. ${c.summary}. ${c.when || ""}`))}
                      style={styles.audioBtn}
                    >
                      <Icon name={playing ? "pause" : "volume-2"} size={14} color={colors.brandPrimary} />
                      <Text style={styles.audioText}>{playing ? "Pause" : "Listen"}</Text>
                    </Pressable>
                  </View>
                </View>
              )}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function Row({ icon, color, text }: { icon: string; color: string; text: string }) {
  return (
    <View style={styles.listRow}>
      <Icon name={icon as any} size={13} color={color} />
      <Text style={styles.listText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider },
  title: { fontSize: 26, fontWeight: "800", color: colors.onSurface, letterSpacing: -0.5 },
  sub: { fontSize: 13, color: colors.muted, marginTop: 2 },
  modeRow: { gap: spacing.sm, paddingTop: spacing.md, paddingRight: spacing.lg },
  modeChip: { height: 36, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", flexShrink: 0, borderWidth: 1, borderColor: colors.border },
  modeChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  modeChipText: { color: colors.onSurfaceSecondary, fontWeight: "700", fontSize: 13 },
  modeChipTextActive: { color: colors.onBrandPrimary },

  scroll: { padding: spacing.lg, paddingBottom: 100 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  cardTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginTop: 6 },
  outlook: { fontSize: 12, color: colors.muted, marginTop: 2 },
  summary: { fontSize: 13, color: colors.onSurfaceSecondary, lineHeight: 19, marginTop: spacing.sm },
  expanded: { marginTop: spacing.md, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.divider },
  sectionLabel: { fontSize: 11, color: colors.muted, fontWeight: "700", textTransform: "uppercase", letterSpacing: 1, marginTop: spacing.sm, marginBottom: 4 },
  listRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 3 },
  listText: { color: colors.onSurface, fontSize: 13 },
  when: { color: colors.onSurface, fontSize: 13, fontStyle: "italic" },

  audioBtn: { flexDirection: "row", gap: 6, alignItems: "center", paddingHorizontal: spacing.md, paddingVertical: 8, backgroundColor: colors.brandSecondary, borderRadius: radius.pill },
  audioText: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
});
