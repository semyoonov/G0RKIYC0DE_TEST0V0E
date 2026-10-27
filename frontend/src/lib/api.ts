import type {
  AssistantEvent,
  AuthSession,
  ChatReply,
  LinkCodeResponse,
  Meta,
  SessionPlatform,
} from "../types";
import type { ConversationPhase } from "./conversation";
import { SpeechCache, speechCacheKey } from "./speechCache";

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

export interface ChatRequestOptions {
  closing?: boolean;
  voice?: string;
}

/**
 * Text answers arrive without speech (`speak: false`), so the reply can render
 * while the voice is synthesised in a separate, abortable request.
 */
export async function postChat(
  text: string,
  clientId: string,
  options: ChatRequestOptions = {},
): Promise<ChatReply> {
  const payload: {
    text: string;
    client_id: string;
    speak: boolean;
    closing?: boolean;
    voice?: string;
  } = {
    text,
    client_id: clientId,
    speak: false,
  };
  if (options.closing) payload.closing = true;
  if (options.voice) payload.voice = options.voice;
  return requestWithSession<ChatReply>("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const SPEECH_TEXT_LIMIT = 4000;

export interface SpeechResult {
  audio: string | null;
  audio_mime: string | null;
  audio_format?: string | null;
}

/** Answers already voiced in this page session; repeats skip the network. */
const speechCache = new SpeechCache();

/** Synthesises speech for an already rendered reply; abortable by the caller. */
export async function postSpeech(
  text: string,
  voice = "",
  signal?: AbortSignal,
): Promise<SpeechResult> {
  const capped = text.slice(0, SPEECH_TEXT_LIMIT);
  const key = speechCacheKey(capped, voice);
  const cached = speechCache.get(key);
  if (cached) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const restored: SpeechResult = { audio: cached.audio, audio_mime: cached.mime };
    if (cached.format) restored.audio_format = cached.format;
    return restored;
  }

  const payload: { text: string; voice?: string } = { text: capped };
  if (voice) payload.voice = voice;
  const result = await requestWithSession<SpeechResult>("/api/speech", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (result.audio) {
    speechCache.set(key, {
      audio: result.audio,
      mime: result.audio_mime,
      format: result.audio_format,
    });
  }
  return result;
}

/** Test hook: forget every cached answer. */
export function clearSpeechCache(): void {
  speechCache.clear();
}

const TELEMETRY_DETAIL_LIMIT = 180;

/**
 * Fire-and-forget diagnostics for the hands-free loop. It never returns a
 * promise the caller could await and never throws: telemetry is best effort.
 */
export function reportTelemetry(
  event: string,
  phase: ConversationPhase | string,
  detail = "",
): void {
  try {
    const body = JSON.stringify({
      event,
      phase,
      detail: String(detail).slice(0, TELEMETRY_DETAIL_LIMIT),
    });
    void fetch("/api/telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }).catch(() => {});
  } catch {
    // A failed telemetry post must never reach the user.
  }
}

/**
 * Warms the model for the next hands-free turn. It is best-effort by design:
 * every failure is swallowed so the conversation never waits on it.
 */
export async function warmupChat(): Promise<void> {
  try {
    await fetch("/api/chat/warmup", withAuthorization({ method: "POST" }));
  } catch {
    // A warmup failure must stay invisible to the user.
  }
}

export async function postVoice(blob: Blob, clientId: string, voice?: string): Promise<ChatReply> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `voice.${extension}`);
  form.append("client_id", clientId);
  if (voice) form.append("voice", voice);
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
