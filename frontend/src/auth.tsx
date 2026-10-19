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
  is_admin?: boolean;
  access?: { tier: string; source?: string | null; trial_days_left?: number; trial_ends_at?: string; renews_at?: string | null };
};

export type SignupPending = { email: string; resend_in: number; expires_in: number; attempts_left: number };

type AuthCtx = {
  user: User | null;
  loading: boolean;
  refresh: () => Promise<void>;
  signInEmail: (email: string, password: string) => Promise<void>;
  signUpEmail: (email: string, password: string, name?: string) => Promise<SignupPending>;
  verifySignup: (email: string, code: string) => Promise<void>;
  resetPassword: (email: string, code: string, newPassword: string) => Promise<void>;
  resendSignupCode: (email: string) => Promise<SignupPending>;
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

  // Sign-up is two steps: this emails a 6-digit code; the account is created by verifySignup.
  const signUpEmail = (email: string, password: string, name?: string): Promise<SignupPending> =>
    api("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password, name }) });

  const resendSignupCode = (email: string): Promise<SignupPending> =>
    api("/api/auth/register/resend", { method: "POST", body: JSON.stringify({ email }) });

  const verifySignup = async (email: string, code: string) => {
    const r = await api("/api/auth/register/verify", { method: "POST", body: JSON.stringify({ email, code }) });
    await saveToken(r.session_token);
    setUser(r.user);
    await refresh();
  };

  // Sets the new password, signs out every other device and signs this one in.
  const resetPassword = async (email: string, code: string, newPassword: string) => {
    const r = await api("/api/auth/password-reset/confirm", { method: "POST", body: JSON.stringify({ email, code, new_password: newPassword }) });
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
    <Ctx.Provider value={{ user, loading, refresh, signInEmail, signUpEmail, verifySignup, resetPassword, resendSignupCode, exchangeSessionId, signOut }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
