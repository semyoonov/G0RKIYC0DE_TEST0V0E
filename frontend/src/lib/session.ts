import { useSyncExternalStore } from "react";

import type { AuthSession } from "../types";
import {
  ApiError,
  clearSessionToken,
  errorMessage,
  fetchMe,
  loginAccount,
  openGuestSession,
  openSession,
  readSessionToken,
  registerAccount,
  setSessionRecovery,
  writeSessionToken,
} from "./api";
import { detectLaunch, type Platform } from "./platform";

export type SessionStatus = "loading" | "ready" | "error";

export interface SessionFallback {
  platform: Platform;
  reason: string;
}

export interface SessionState {
  status: SessionStatus;
  session: AuthSession | null;
  fallback: SessionFallback | null;
  error: string | null;
}

const INITIAL_STATE: SessionState = {
  status: "loading",
  session: null,
  fallback: null,
  error: null,
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
  });
  return session;
}

function fail(error: unknown, fallback: SessionFallback | null = state.fallback): void {
  patch({ status: "error", error: errorMessage(error), fallback });
}

async function openPlatformSession(platform: Platform, payload: string): Promise<AuthSession> {
  // Мини-приложение обязано подтвердить свою платформенную личность: токен
  // другого клиента не сохраняется молча, если проверка запуска не прошла.
  clearSessionToken();
  patch({ status: "loading", error: null });
  try {
    const session = await openSession(platform, payload);
    applySession(session);
    return state.session as AuthSession;
  } catch (error) {
    fail(error, { platform, reason: errorMessage(error) });
    throw error;
  }
}

async function startGuest(): Promise<AuthSession> {
  const session = await openGuestSession();
  applySession(session);
  return state.session as AuthSession;
}

async function runBootstrap(): Promise<void> {
  patch({ status: "loading", error: null });
  try {
    const launch = detectLaunch();
    // В мини-приложении пользователя определяют подписанные данные запуска.
    if (launch.platform !== "web" && launch.payload) {
      await openPlatformSession(launch.platform, launch.payload);
      return;
    }

    const stored = readSessionToken();
    if (stored) {
      try {
        applySession(await fetchMe(stored));
        return;
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) {
          fail(error);
          return;
        }
        clearSessionToken();
      }
    }

    await startGuest();
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
  try {
    const session = await startGuest();
    return session.token;
  } catch {
    return null;
  }
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

/** Регистрирует текущий аккаунт, сохраняя его задачи и привязанные платформы. */
export async function registerWithPassword(email: string, password: string): Promise<AuthSession> {
  applySession(await registerAccount(email.trim(), password));
  return state.session as AuthSession;
}

/** Входит в существующий аккаунт и привязывает к нему текущую платформу. */
export async function loginWithPassword(email: string, password: string): Promise<AuthSession> {
  applySession(await loginAccount(email.trim(), password));
  return state.session as AuthSession;
}

/** Выходит из аккаунта и продолжает в новой гостевой сессии. */
export async function leaveAccount(): Promise<void> {
  clearSessionToken();
  patch({ status: "loading", session: null, error: null, fallback: null });
  await startGuest().catch((error: unknown) => fail(error));
}

export function resetSession(): void {
  clearSessionToken();
  bootstrapPromise = null;
  recoveryPromise = null;
  publish(INITIAL_STATE);
}

setSessionRecovery(recoverSessionOnce);
