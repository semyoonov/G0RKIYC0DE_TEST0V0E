import type {
  AssistantEvent,
  AuthSession,
  ChatReply,
  LinkCodeResponse,
  Meta,
  SessionPlatform,
} from "../types";

const CLIENT_STORAGE_KEY = "assistant_client_id";
export const SESSION_TOKEN_STORAGE_KEY = "assistant_session_token";
export const NETWORK_ERROR_TEXT = "Не удалось связаться с сервером. Попробуйте позже.";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let memoryToken: string | null = null;

function localStorageOrNull(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readSessionToken(): string | null {
  try {
    const stored = localStorageOrNull()?.getItem(SESSION_TOKEN_STORAGE_KEY);
    if (stored) return stored;
  } catch {
    // Private mode can block localStorage.
  }
  return memoryToken;
}

export function writeSessionToken(token: string): void {
  memoryToken = token;
  try {
    localStorageOrNull()?.setItem(SESSION_TOKEN_STORAGE_KEY, token);
  } catch {
    // The token stays valid for the current page session.
  }
}

export function clearSessionToken(): void {
  memoryToken = null;
  try {
    localStorageOrNull()?.removeItem(SESSION_TOKEN_STORAGE_KEY);
  } catch {
    // Nothing to clear when storage is unavailable.
  }
}

type SessionRecovery = () => Promise<string | null>;

let recoverSession: SessionRecovery | null = null;

/** The session store registers how to obtain a fresh token after a 401. */
export function setSessionRecovery(handler: SessionRecovery | null): void {
  recoverSession = handler;
}

export function readClientId(): string {
  try {
    const stored = window.localStorage.getItem(CLIENT_STORAGE_KEY);
    if (stored) return stored;
  } catch {
    // Private mode can block localStorage.
  }
  const generated =
    typeof window.crypto?.randomUUID === "function"
      ? window.crypto.randomUUID()
      : `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    window.localStorage.setItem(CLIENT_STORAGE_KEY, generated);
  } catch {
    // The identifier stays valid for the current page session.
  }
  return generated;
}

function withAuthorization(init: RequestInit, token: string | null = readSessionToken()): RequestInit {
  if (!token) return init;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json().catch(() => ({}))) as T & { detail?: string };
  if (!response.ok) {
    throw new ApiError(payload.detail || "Не удалось выполнить запрос", response.status);
  }
  return payload;
}

/**
 * Account-scoped endpoints retry once with a freshly issued token. The retry
 * never repeats for a second 401, so a broken session cannot loop.
 */
async function requestWithSession<T>(path: string, init: RequestInit): Promise<T> {
  const token = readSessionToken();
  const response = await fetch(path, withAuthorization(init, token));
  if (response.status === 401 && token) {
    clearSessionToken();
    const fresh = recoverSession ? await recoverSession().catch(() => null) : null;
    if (fresh) {
      return readJson<T>(await fetch(path, withAuthorization(init, fresh)));
    }
  }
  return readJson<T>(response);
}

async function requestWithToken<T>(path: string, init: RequestInit): Promise<T> {
  return readJson<T>(await fetch(path, withAuthorization(init)));
}

export async function fetchMeta(): Promise<Meta> {
  return readJson<Meta>(await fetch("/api/meta", withAuthorization({})));
}

export async function openSession(
  platform: SessionPlatform,
  payload: string | null,
  clientId: string | null,
): Promise<AuthSession> {
  return readJson<AuthSession>(
    await fetch("/api/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, payload, client_id: clientId }),
    }),
  );
}

export async function fetchMe(token: string): Promise<AuthSession> {
  return readJson<AuthSession>(
    await fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    }),
  );
}

export async function requestAuthCode(): Promise<LinkCodeResponse> {
  return requestWithToken<LinkCodeResponse>("/api/auth/code", { method: "POST" });
}

export async function linkIdentity(code: string): Promise<AuthSession> {
  return requestWithToken<AuthSession>("/api/auth/link", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

export async function postChat(text: string, clientId: string, speak = false): Promise<ChatReply> {
  return requestWithSession<ChatReply>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, client_id: clientId, speak }),
  });
}

export async function postVoice(blob: Blob, clientId: string): Promise<ChatReply> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `voice.${extension}`);
  form.append("client_id", clientId);
  return requestWithSession<ChatReply>("/api/voice", { method: "POST", body: form });
}

export async function fetchEvents(clientId: string, period = "today"): Promise<AssistantEvent[]> {
  const query = new URLSearchParams({ client_id: clientId, period });
  const payload = await requestWithSession<{ events: AssistantEvent[] }>(
    `/api/events?${query.toString()}`,
    {},
  );
  return payload.events;
}

export async function completeEvent(eventId: number, clientId: string): Promise<AssistantEvent> {
  const query = new URLSearchParams({ client_id: clientId });
  return requestWithSession<AssistantEvent>(
    `/api/events/${encodeURIComponent(String(eventId))}/complete?${query.toString()}`,
    { method: "POST" },
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError && /fetch|network/i.test(error.message)) return NETWORK_ERROR_TEXT;
  if (error instanceof Error && error.message) return error.message;
  return "Не удалось получить ответ. Попробуйте ещё раз.";
}
