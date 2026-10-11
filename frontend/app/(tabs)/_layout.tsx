import React from "react";
import { Platform } from "react-native";
import { Tabs } from "expo-router";
import Icon from "@react-native-vector-icons/feather";

import { colors } from "@/src/theme";

export const usesNativeTabs = Platform.OS === "ios" && parseInt(String(Platform.Version), 10) >= 26;

export default function TabsLayout() {
  // Keep layout simple across iOS/Android/web using JS Tabs
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.brandPrimary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          ...(Platform.OS === "web" ? { height: 64 } : {}),
        },
        tabBarItemStyle: { alignSelf: "center" },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{ title: "Home", tabBarIcon: ({ color, size }) => <Icon name="home" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="options"
        options={{ title: "Options", tabBarIcon: ({ color, size }) => <Icon name="layers" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="stocks"
        options={{ title: "Stocks", tabBarIcon: ({ color, size }) => <Icon name="trending-up" size={size} color={color} /> }}
      />
      <Tabs.Screen
        name="profile"
        options={{ title: "Profile", tabBarIcon: ({ color, size }) => <Icon name="user" size={size} color={color} /> }}
      />
    </Tabs>
  );
}
