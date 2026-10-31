import type {
  AssistantEvent,
  AuthSession,
  ChatReply,
  Meta,
  SessionPlatform,
} from "../types";
import type { ConversationPhase } from "./conversation";
import { SpeechCache, speechCacheKey } from "./speechCache";

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
    // Приватный режим может блокировать localStorage.
  }
  return memoryToken;
}

export function writeSessionToken(token: string): void {
  memoryToken = token;
  try {
    localStorageOrNull()?.setItem(SESSION_TOKEN_STORAGE_KEY, token);
  } catch {
    // Токен остаётся рабочим до конца сеанса страницы.
  }
}

export function clearSessionToken(): void {
  memoryToken = null;
  try {
    localStorageOrNull()?.removeItem(SESSION_TOKEN_STORAGE_KEY);
  } catch {
    // Хранилище недоступно — очищать нечего.
  }
}

type SessionRecovery = () => Promise<string | null>;

let recoverSession: SessionRecovery | null = null;

/** Хранилище сессии регистрирует здесь способ получить свежий токен после 401. */
export function setSessionRecovery(handler: SessionRecovery | null): void {
  recoverSession = handler;
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
 * Эндпоинты аккаунта повторяются один раз со свежим токеном. Повтор не
 * срабатывает на второй 401, поэтому сломанная сессия не зацикливается.
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
): Promise<AuthSession> {
  return readJson<AuthSession>(
    await fetch("/api/auth/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, payload }),
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

export async function openGuestSession(): Promise<AuthSession> {
  return readJson<AuthSession>(await fetch("/api/auth/guest", { method: "POST" }));
}

export async function registerAccount(email: string, password: string): Promise<AuthSession> {
  return requestWithToken<AuthSession>("/api/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function loginAccount(email: string, password: string): Promise<AuthSession> {
  return requestWithToken<AuthSession>("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export interface ChatRequestOptions {
  closing?: boolean;
  voice?: string;
}

/**
 * Текстовый ответ приходит без озвучки (`speak: false`), поэтому ответ
 * показывается сразу, а голос синтезируется отдельным прерываемым запросом.
 */
export async function postChat(
  text: string,
  options: ChatRequestOptions = {},
): Promise<ChatReply> {
  const payload: {
    text: string;
    speak: boolean;
    closing?: boolean;
    voice?: string;
  } = {
    text,
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

/** Уже озвученные за сеанс ответы: повтор не ходит в сеть. */
const speechCache = new SpeechCache();

/** Синтез речи для уже показанного ответа; вызывающий может прервать запрос. */
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

/** Только для тестов: забыть все закэшированные ответы. */
export function clearSpeechCache(): void {
  speechCache.clear();
}

const TELEMETRY_DETAIL_LIMIT = 180;

/**
 * Диагностика цикла без рук «выстрелил и забыл»: функция не отдаёт промис,
 * который можно дождаться, и не бросает исключений — телеметрия необязательна.
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
    // Сбой отправки телеметрии не должен доходить до пользователя.
  }
}

/**
 * Прогревает модель для следующего хода без рук. Ошибки глушатся намеренно:
 * разговор не должен ждать прогрева.
 */
export async function warmupChat(): Promise<void> {
  try {
    await fetch("/api/chat/warmup", withAuthorization({ method: "POST" }));
  } catch {
    // Сбой прогрева остаётся невидимым для пользователя.
  }
}

export async function postVoice(blob: Blob, voice?: string): Promise<ChatReply> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `voice.${extension}`);
  if (voice) form.append("voice", voice);
  return requestWithSession<ChatReply>("/api/voice", { method: "POST", body: form });
}

export async function fetchEvents(period = "today"): Promise<AssistantEvent[]> {
  const query = new URLSearchParams({ period });
  const payload = await requestWithSession<{ events: AssistantEvent[] }>(
    `/api/events?${query.toString()}`,
    {},
  );
  return payload.events;
}

export async function completeEvent(eventId: number): Promise<AssistantEvent> {
  return requestWithSession<AssistantEvent>(
    `/api/events/${encodeURIComponent(String(eventId))}/complete`,
    { method: "POST" },
  );
}

export async function downloadCalendarIcs(): Promise<void> {
  const token = readSessionToken();
  const response = await fetch("/api/calendar/export.ics", withAuthorization({}, token));
  if (!response.ok) {
    throw new ApiError("Не удалось экспортировать календарь", response.status);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "gorkycode_calendar.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError && /fetch|network/i.test(error.message)) return NETWORK_ERROR_TEXT;
  if (error instanceof Error && error.message) return error.message;
  return "Не удалось получить ответ. Попробуйте ещё раз.";
}
