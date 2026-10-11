import { QueryClientProvider } from "@tanstack/react-query";
import { Stack, useRouter, useSegments } from "expo-router";
import { useEffect } from "react";
import { LogBox, Platform, View, ActivityIndicator } from "react-native";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import * as Notifications from "expo-notifications";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { ErrorBoundary } from "@/src/components/error-boundary";
import { queryClient } from "@/src/query-client";
import { AuthProvider, useAuth } from "@/src/auth";
import { colors } from "@/src/theme";
import { registerForPush } from "@/src/push";

LogBox.ignoreAllLogs(true);
WebBrowser.maybeCompleteAuthSession();

// Push: module-scope setup (web-guarded)
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
}
if (Platform.OS === "android") {
  Notifications.setNotificationChannelAsync("default", {
    name: "Default",
    importance: Notifications.AndroidImportance.MAX,
    sound: "default",
  });
}

function extractSessionId(url: string | null | undefined): string | null {
  if (!url) return null;
  const m = url.match(/[?#&]session_id=([^&#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, exchangeSessionId } = useAuth();
  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    let sub: any;
    const tryExchange = async (url: string | null) => {
      const sid = extractSessionId(url);
      if (!sid) return;
      try {
        await exchangeSessionId(sid);
        if (Platform.OS === "web") {
          try {
            const u = new URL(window.location.href);
            u.hash = "";
            u.searchParams.delete("session_id");
            window.history.replaceState(window.history.state, "", u.toString());
          } catch {}
        }
      } catch (e) { console.warn("session exchange failed", e); }
    };

    if (Platform.OS === "web" && typeof window !== "undefined") {
      tryExchange(window.location.href);
    } else {
      Linking.getInitialURL().then(tryExchange);
      sub = Linking.addEventListener("url", (e) => tryExchange(e.url));
    }
    return () => { sub?.remove?.(); };
  }, [exchangeSessionId]);

  // Push notification tap handlers (native-only)
  useEffect(() => {
    if (Platform.OS === "web") return;

    const tapSub = Notifications.addNotificationResponseReceivedListener((response) => {
      const data = (response.notification.request.content.data || {}) as any;
      const url = data.deeplink || data.action_url;
      if (!url) return;
      if (typeof url === "string" && url.startsWith("http")) Linking.openURL(url);
      else router.push(url);
    });

    Notifications.getLastNotificationResponseAsync().then((response) => {
      if (!response) return;
      const data = (response.notification.request.content.data || {}) as any;
      const url = data.deeplink || data.action_url;
      if (url) {
        if (typeof url === "string" && url.startsWith("http")) Linking.openURL(url);
        else router.push(url);
      }
    });

    // Weekly nudge if denied
    (async () => {
      const { status, canAskAgain } = await Notifications.getPermissionsAsync();
      if (status !== "denied" || canAskAgain) return;
      const lastNudge = await AsyncStorage.getItem("pushNudgeAt");
      const oneWeek = 7 * 24 * 60 * 60 * 1000;
      if (lastNudge && Date.now() - Number(lastNudge) <= oneWeek) return;
      // Store so we don't spam
      await AsyncStorage.setItem("pushNudgeAt", String(Date.now()));
    })();

    return () => { tapSub.remove(); };
  }, [router]);

  // Register for push whenever user is set
  useEffect(() => {
    if (user?.user_id) registerForPush(user.user_id);
  }, [user?.user_id]);

  useEffect(() => {
    if (loading) return;
    const inAuth = segments[0] === "(auth)";
    if (!user && !inAuth) {
      router.replace("/(auth)/login");
    } else if (user && inAuth) {
      if (!user.plan) router.replace("/(auth)/plan");
      else if (!user.questionnaire_complete) router.replace("/(auth)/questionnaire");
      else if (!user.consent_signed) router.replace("/(auth)/consent");
      else router.replace("/(tabs)");
    } else if (user && !inAuth) {
      if (!user.plan) router.replace("/(auth)/plan");
      else if (!user.questionnaire_complete) router.replace("/(auth)/questionnaire");
      else if (!user.consent_signed) router.replace("/(auth)/consent");
    }
  }, [user, loading, segments, router]);

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </View>
    );
  }
  return <>{children}</>;
}

export default function RootLayout() {
  return (
    <ErrorBoundary>
      <GestureHandlerRootView style={{ flex: 1 }}>
        <SafeAreaProvider>
          <QueryClientProvider client={queryClient}>
            <KeyboardProvider>
              <AuthProvider>
                <AuthGate>
                  <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.surface } }} />
                </AuthGate>
              </AuthProvider>
            </KeyboardProvider>
          </QueryClientProvider>
        </SafeAreaProvider>
      </GestureHandlerRootView>
    </ErrorBoundary>
  );
}
