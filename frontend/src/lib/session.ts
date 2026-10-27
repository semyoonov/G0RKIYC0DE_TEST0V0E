import { useSyncExternalStore } from "react";

import type { AuthSession, LinkCodeResponse } from "../types";
import {
  ApiError,
  clearSessionToken,
  errorMessage,
  fetchMe,
  linkIdentity,
  openSession,
  readClientId,
  readSessionToken,
  requestAuthCode,
  setSessionRecovery,
  writeSessionToken,
} from "./api";
import { detectLaunch, readLinkParam, type Platform } from "./platform";

export type SessionStatus = "idle" | "loading" | "ready" | "error";

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

function isPlatformUnavailable(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 503);
}

async function loginFresh(): Promise<AuthSession | null> {
  const launch = detectLaunch();
  const clientId = readClientId();
  patch({ status: "loading", error: null });
  try {
    const session = await openSession(
      launch.platform,
      launch.payload,
      launch.platform === "web" ? clientId : null,
    );
    return applySession(session);
  } catch (error) {
    if (launch.platform === "web" || !isPlatformUnavailable(error)) {
      fail(error);
      return null;
    }
    const fallback: SessionFallback = { platform: launch.platform, reason: errorMessage(error) };
    try {
      const session = await openSession("web", null, clientId);
      return applySession(session, fallback);
    } catch (webError) {
      fail(webError, fallback);
      return null;
    }
  }
}

async function runBootstrap(): Promise<void> {
  patch({ status: "loading", error: null });
  try {
    const launch = detectLaunch();
    // Inside a mini app the launch data names the account, so a stored web token must not win.
    if (launch.platform !== "web" && launch.payload) {
      await loginFresh();
      return;
    }
    const linkCode = readLinkParam();
    const stored = readSessionToken();
    let currentSession: AuthSession | null = null;
    if (stored) {
      try {
        currentSession = await fetchMe(stored);
        applySession(currentSession);
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) {
          fail(error);
          return;
        }
        clearSessionToken();
      }
    }
    if (!currentSession) {
      currentSession = await loginFresh();
    }
    if (linkCode && currentSession) {
      try {
        await linkWithCode(linkCode);
      } catch {
        // Link code might be expired or already redeemed; continue with current session
      }
    }
  } catch (error) {
    fail(error);
  }
}

/**
 * Restores or opens the account session. Safe to call from startup and from a
 * retry button; concurrent callers share one login attempt.
 */
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
  const session = await loginFresh();
  return session?.token ?? null;
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
  return () => {
    listeners.delete(listener);
  };
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

/** Reports a redeemed link once, so the success line does not repeat on refresh. */
export function consumeLinkRedeemed(): boolean {
  if (!state.linkRedeemed) return false;
  patch({ linkRedeemed: false });
  return true;
}

/** Drops the in-memory snapshot and the persisted token; used by tests and logout flows. */
export function resetSession(): void {
  clearSessionToken();
  bootstrapPromise = null;
  recoveryPromise = null;
  publish(INITIAL_STATE);
}

setSessionRecovery(recoverSessionOnce);
