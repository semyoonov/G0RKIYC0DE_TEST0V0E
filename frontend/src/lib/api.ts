import type { AssistantEvent, ChatReply, Meta } from "../types";

const CLIENT_STORAGE_KEY = "assistant_client_id";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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

async function readJson<T>(response: Response): Promise<T> {
  const payload = (await response.json().catch(() => ({}))) as T & { detail?: string };
  if (!response.ok) {
    throw new ApiError(payload.detail || "Не удалось выполнить запрос", response.status);
  }
  return payload;
}

export async function fetchMeta(): Promise<Meta> {
  return readJson<Meta>(await fetch("/api/meta"));
}

export async function postChat(text: string, clientId: string, speak = false): Promise<ChatReply> {
  return readJson<ChatReply>(
    await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, client_id: clientId, speak }),
    }),
  );
}

export async function postVoice(blob: Blob, clientId: string): Promise<ChatReply> {
  const form = new FormData();
  const extension = blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", blob, `voice.${extension}`);
  form.append("client_id", clientId);
  return readJson<ChatReply>(await fetch("/api/voice", { method: "POST", body: form }));
}

export async function completeEvent(eventId: number, clientId: string): Promise<AssistantEvent> {
  const query = new URLSearchParams({ client_id: clientId });
  return readJson<AssistantEvent>(
    await fetch(`/api/events/${encodeURIComponent(String(eventId))}/complete?${query.toString()}`, {
      method: "POST",
    }),
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return "Не удалось получить ответ. Попробуйте ещё раз.";
}
