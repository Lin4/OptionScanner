import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, saveToken, getToken, clearToken } from "./api";

export type User = {
  user_id: string;
  email: string;
  name: string;
  picture?: string | null;
  plan?: string | null;
  questionnaire_complete?: boolean;
  consent_signed?: boolean;
  questionnaire?: Record<string, any>;
  auth_method?: "email" | "google";
  created_at?: string;
  access?: { tier: string; source?: string | null; trial_days_left?: number; trial_ends_at?: string; renews_at?: string | null };
};

type AuthCtx = {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signInEmail: (email: string, password: string) => Promise<void>;
  signUpEmail: (email: string, password: string, name?: string) => Promise<void>;
  exchangeSessionId: (session_id: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

const processedSessionIds = new Set<string>();

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const t = await getToken();
    if (!t) { setUser(null); setLoading(false); return; }
    try {
      const r = await api("/api/auth/me");
      setUser(r.user);
    } catch {
      await clearToken();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const signInEmail = async (email: string, password: string) => {
    const r = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    await saveToken(r.session_token);
    setUser(r.user);
    await refresh(); // pull full profile incl. membership access
  };

  const signUpEmail = async (email: string, password: string, name?: string) => {
    const r = await api("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, name }) });
    await saveToken(r.session_token);
    setUser(r.user);
    await refresh();
  };

  const exchangeSessionId = async (session_id: string) => {
    if (processedSessionIds.has(session_id)) return;
    processedSessionIds.add(session_id);
    const r = await api("/api/auth/session", { method: "POST", body: JSON.stringify({ session_id }) });
    await saveToken(r.session_token);
    setUser(r.user);
    await refresh();
  };

  const signOut = async () => {
    try { await api("/api/auth/logout", { method: "POST" }); } catch {}
    await clearToken();
    setUser(null);
  };

  return (
    <Ctx.Provider value={{ user, loading, refresh, signInEmail, signUpEmail, exchangeSessionId, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
