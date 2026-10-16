import React, { createContext, useContext, useEffect, useMemo } from "react";
import { Platform } from "react-native";
import Purchases, { LOG_LEVEL } from "react-native-purchases";
import type { CustomerInfo, PurchasesPackage } from "react-native-purchases";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const REVENUECAT_TEST_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_TEST_API_KEY;
const REVENUECAT_IOS_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_IOS_API_KEY;
const REVENUECAT_ANDROID_API_KEY = process.env.EXPO_PUBLIC_REVENUECAT_ANDROID_API_KEY;

export const REVENUECAT_ENTITLEMENT_IDENTIFIER = "pro";
// RevenueCat package lookup key -> OptiScreen tier
export const PACKAGE_TIER: Record<string, "simple" | "advance" | "expert"> = {
  $rc_monthly: "simple",
  advance_monthly: "advance",
  expert_monthly: "expert",
};

export const rcEnabled = Platform.OS !== "web" || __DEV__; // web preview uses the Test Store
export const rcSimulated = Platform.OS === "web" || __DEV__; // Test Store purchases are simulated

function getRevenueCatApiKey() {
  if (!REVENUECAT_TEST_API_KEY || !REVENUECAT_IOS_API_KEY || !REVENUECAT_ANDROID_API_KEY) {
    throw new Error("RevenueCat public API keys not found");
  }
  if (Platform.OS === "web" || __DEV__) return REVENUECAT_TEST_API_KEY;
  if (Platform.OS === "ios") return REVENUECAT_IOS_API_KEY;
  if (Platform.OS === "android") return REVENUECAT_ANDROID_API_KEY;
  return REVENUECAT_TEST_API_KEY;
}

export function initializeRevenueCat() {
  if (!rcEnabled) return;
  Purchases.setLogLevel(__DEV__ ? LOG_LEVEL.DEBUG : LOG_LEVEL.WARN);
  Purchases.configure({ apiKey: getRevenueCatApiKey() });
}

function useSubscriptionContext() {
  const queryClient = useQueryClient();

  const customerInfoQuery = useQuery({
    queryKey: ["revenuecat", "customer-info"],
    queryFn: () => Purchases.getCustomerInfo(),
    enabled: rcEnabled,
    staleTime: 60 * 1000,
  });

  // Current app user id (originalAppUserId can stay anonymous after an alias in Browser Mode)
  const appUserIdQuery = useQuery({
    queryKey: ["revenuecat", "app-user-id"],
    queryFn: () => Purchases.getAppUserID(),
    enabled: rcEnabled,
    staleTime: 30 * 1000,
  });

  const offeringsQuery = useQuery({
    queryKey: ["revenuecat", "offerings"],
    queryFn: () => Purchases.getOfferings(),
    enabled: rcEnabled,
    staleTime: 300 * 1000,
  });

  useEffect(() => {
    if (!rcEnabled) return;
    const listener = (info: CustomerInfo) => queryClient.setQueryData(["revenuecat", "customer-info"], info);
    Purchases.addCustomerInfoUpdateListener(listener);
    return () => { Purchases.removeCustomerInfoUpdateListener(listener); };
  }, [queryClient]);

  const purchaseMutation = useMutation({
    mutationFn: async (packageToPurchase: PurchasesPackage) => {
      const id = await Purchases.getAppUserID();
      if (!id || id.startsWith("$RCAnonymousID:")) throw new Error("identity_not_ready");
      const { customerInfo } = await Purchases.purchasePackage(packageToPurchase);
      return customerInfo;
    },
  });

  const restoreMutation = useMutation({ mutationFn: () => Purchases.restorePurchases() });

  const info = customerInfoQuery.data;
  const isSubscribed = info?.entitlements.active?.[REVENUECAT_ENTITLEMENT_IDENTIFIER] !== undefined;
  const appUserId = appUserIdQuery.data;
  const identityReady = !!appUserId && !appUserId.startsWith("$RCAnonymousID:");

  // Which tier is active: map the active product back to its package lookup key
  const rcTier = useMemo(() => {
    if (!isSubscribed) return null;
    const active = new Set(info?.activeSubscriptions || []);
    let best: "simple" | "advance" | "expert" | null = null;
    const rank = { simple: 1, advance: 2, expert: 3 };
    for (const pkg of offeringsQuery.data?.current?.availablePackages || []) {
      const t = PACKAGE_TIER[pkg.identifier];
      if (t && active.has(pkg.product.identifier) && (!best || rank[t] > rank[best])) best = t;
    }
    return best || "simple";
  }, [isSubscribed, info, offeringsQuery.data]);

  return {
    customerInfo: info,
    offerings: offeringsQuery.data,
    isSubscribed,
    rcTier,
    identityReady,
    isLoading: customerInfoQuery.isLoading || offeringsQuery.isLoading,
    purchase: purchaseMutation.mutateAsync,
    restore: restoreMutation.mutateAsync,
    isPurchasing: purchaseMutation.isPending,
    isRestoring: restoreMutation.isPending,
  };
}

type SubscriptionContextValue = ReturnType<typeof useSubscriptionContext>;
const Context = createContext<SubscriptionContextValue | null>(null);

export function SubscriptionProvider({ children }: { children: React.ReactNode }) {
  const value = useSubscriptionContext();
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSubscription() {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useSubscription must be used within a SubscriptionProvider");
  return ctx;
}
