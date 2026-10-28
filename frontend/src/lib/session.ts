import { useSyncExternalStore } from "react";

import type { AuthSession, LinkCodeResponse } from "../types";
import {
  ApiError,
  clearSessionToken,
  errorMessage,
  fetchMe,
  linkIdentity,
  openSession,
  readSessionToken,
  requestAuthCode,
  requestEmailCode as requestEmailCodeApi,
  setSessionRecovery,
  verifyEmailCode as verifyEmailCodeApi,
  writeSessionToken,
} from "./api";
import { detectLaunch, readLinkParam, type Platform } from "./platform";

export type SessionStatus = "idle" | "loading" | "ready" | "unauthenticated" | "error";

export interface SessionFallback {
  platform: Platform;
  reason: string;
}

export interface SessionState {
  status: SessionStatus;
  session: AuthSession | null;
  fallback: SessionFallback | null;
  error: string | null;
  linkRedeemed: boolean;
}

const INITIAL_STATE: SessionState = {
  status: "idle",
  session: null,
  fallback: null,
  error: null,
  linkRedeemed: false,
};

let state: SessionState = INITIAL_STATE;
let bootstrapPromise: Promise<void> | null = null;
let recoveryPromise: Promise<string | null> | null = null;
const listeners = new Set<() => void>();

function publish(next: SessionState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

function patch(changes: Partial<SessionState>): void {
  publish({ ...state, ...changes });
}

function applySession(session: AuthSession, fallback: SessionFallback | null = null): AuthSession {
  writeSessionToken(session.token);
  patch({
    status: "ready",
    session,
    fallback,
    error: null,
    linkRedeemed: session.link_redeemed,
  });
  return session;
}

function fail(error: unknown, fallback: SessionFallback | null = state.fallback): void {
  patch({ status: "error", error: errorMessage(error), fallback });
}

async function loginFresh(): Promise<AuthSession | null> {
  const launch = detectLaunch();
  if (launch.platform === "web") {
    patch({ status: "unauthenticated", session: null, error: null });
    return null;
  }
  // A mini-app must prove its own platform identity; do not silently retain a
  // token from a different client if the launch validation fails.
  clearSessionToken();
  patch({ status: "loading", error: null });
  try {
    const session = await openSession(launch.platform, launch.payload);
    return applySession(session);
  } catch (error) {
    fail(error, { platform: launch.platform, reason: errorMessage(error) });
    return null;
  }
}

async function maybeRedeemLinkCode(): Promise<void> {
  const code = readLinkParam();
  if (!code || !readSessionToken()) return;
  try {
    await linkWithCode(code);
  } catch {
    // A link code may be expired or unrelated; normal email login still succeeds.
  }
}

async function runBootstrap(): Promise<void> {
  patch({ status: "loading", error: null });
  try {
    const launch = detectLaunch();
    // In a mini app, signed platform launch data identifies the user.
    if (launch.platform !== "web" && launch.payload) {
      await loginFresh();
      return;
    }

    const stored = readSessionToken();
    if (stored) {
      try {
        const current = await fetchMe(stored);
        applySession(current);
        await maybeRedeemLinkCode();
        return;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) {
          fail(error);
          return;
        }
        // Keep a signed legacy web token for one purpose only: the user can
        // verify an email and preserve their old anonymous tasks. Protected API
        // routes reject it until the email verification succeeds.
        if (launch.platform !== "web") clearSessionToken();
      }
    }

    if (launch.platform === "web") {
      patch({ status: "unauthenticated", session: null, fallback: null, error: null });
      return;
    }
    fail(new Error("Откройте мини-приложение из своего мессенджера."));
  } catch (error) {
    fail(error);
  }
}

export function bootstrapSession(): Promise<void> {
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = runBootstrap().finally(() => {
    bootstrapPromise = null;
  });
  return bootstrapPromise;
}

async function recoverSession(): Promise<string | null> {
  if (bootstrapPromise) await bootstrapPromise;
  const existing = readSessionToken();
  if (existing) return existing;
  patch({ status: "unauthenticated", session: null, fallback: null, error: null });
  return null;
}

function recoverSessionOnce(): Promise<string | null> {
  if (recoveryPromise) return recoveryPromise;
  recoveryPromise = recoverSession().finally(() => {
    recoveryPromise = null;
  });
  return recoveryPromise;
}

export function subscribeSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getSessionSnapshot(): SessionState {
  return state;
}

export function useSession(): SessionState {
  return useSyncExternalStore(subscribeSession, getSessionSnapshot, getSessionSnapshot);
}

export function getToken(): string | null {
  return readSessionToken();
}

export async function requestEmailCode(email: string): Promise<void> {
  await requestEmailCodeApi(email.trim());
}

export async function loginWithEmail(email: string, code: string): Promise<AuthSession> {
  const session = await verifyEmailCodeApi(email.trim(), code.trim());
  applySession(session);
  await maybeRedeemLinkCode();
  return session;
}

export async function requestLinkCode(): Promise<LinkCodeResponse> {
  if (!readSessionToken()) {
    throw new ApiError("Войдите в аккаунт, чтобы получить код.", 401);
  }
  return requestAuthCode();
}

export async function linkWithCode(code: string): Promise<AuthSession> {
  const session = await linkIdentity(code.trim());
  return applySession(session);
}

export function consumeLinkRedeemed(): boolean {
  if (!state.linkRedeemed) return false;
  patch({ linkRedeemed: false });
  return true;
}

export function resetSession(): void {
  clearSessionToken();
  bootstrapPromise = null;
  recoveryPromise = null;
  publish(INITIAL_STATE);
}

setSessionRecovery(recoverSessionOnce);
