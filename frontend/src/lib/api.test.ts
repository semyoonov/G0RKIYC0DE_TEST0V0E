import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatReply } from "../types";
import {
  clearSessionToken,
  postChat,
  postSpeech,
  reportTelemetry,
  SESSION_TOKEN_STORAGE_KEY,
  warmupChat,
} from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestAt(index: number): { path: unknown; init: RequestInit | undefined } {
  const call = fetchMock.mock.calls[index];
  if (!call) throw new Error(`request ${index} was not made`);
  return { path: call[0], init: call[1] };
}

function requestBody(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(String(init?.body)) as Record<string, unknown>;
}

const fetchMock = vi.fn<typeof fetch>();

const REPLY: ChatReply = {
  reply: "Готово",
  audio: null,
  audio_mime: null,
  events: [],
  needs_clarification: false,
  intent: null,
};

beforeEach(() => {
  clearSessionToken();
  window.localStorage.clear();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("postChat closing flag", () => {
  it("always asks for text without speech and omits closing when it is false", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));

    await postChat("Привет", "client-anon");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestAt(0).path).toBe("/api/chat");
    const body = requestBody(requestAt(0).init);
    expect(body).toEqual({ text: "Привет", client_id: "client-anon", speak: false });
    expect("closing" in body).toBe(false);
  });

  it("sends closing true for a farewell", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));

    await postChat("Спасибо", "client-anon", { closing: true });

    expect(requestBody(requestAt(0).init)).toEqual({
      text: "Спасибо",
      client_id: "client-anon",
      speak: false,
      closing: true,
    });
  });
});

describe("warmupChat", () => {
  it("posts to the warmup endpoint with the session token and no body", async () => {
    window.localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, "token-1");
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "ok" }));

    await expect(warmupChat()).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/chat/warmup");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-1");
    expect(init?.body).toBeUndefined();
  });

  it("swallows network and server failures", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(warmupChat()).resolves.toBeUndefined();

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Нет доступа." }, 500));
    await expect(warmupChat()).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("postChat voice", () => {
  it("sends the chosen voice and omits it when empty", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    await postChat("Что на завтра?", "client-1", { voice: "Gli-Operator" });
    expect(requestBody(requestAt(0).init)).toMatchObject({ voice: "Gli-Operator" });

    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    await postChat("Что на завтра?", "client-1", { voice: "" });
    expect(requestBody(requestAt(1).init)).not.toHaveProperty("voice");
  });
});

describe("postSpeech", () => {
  it("posts the text with the session token and returns the audio payload", async () => {
    window.localStorage.setItem(SESSION_TOKEN_STORAGE_KEY, "token-2");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ audio: "QUJD", audio_mime: "audio/ogg", audio_format: "opus" }),
    );

    const speech = await postSpeech("Создал задачу", "voice-1");

    expect(speech).toEqual({ audio: "QUJD", audio_mime: "audio/ogg", audio_format: "opus" });
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/speech");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer token-2");
    expect(requestBody(init)).toEqual({ text: "Создал задачу", voice: "voice-1" });
  });

  it("caps the text at 4000 characters and forwards an abort signal", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ audio: null, audio_mime: null }));
    const controller = new AbortController();

    await postSpeech("я".repeat(5_000), "", controller.signal);

    const { init } = requestAt(0);
    expect(String(requestBody(init).text)).toHaveLength(4000);
    expect(init?.signal).toBe(controller.signal);
    expect(requestBody(init)).not.toHaveProperty("voice");
  });
});

describe("reportTelemetry", () => {
  it("posts the event and phase without auth and returns immediately", () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    expect(() => reportTelemetry("phase", "listening")).not.toThrow();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/telemetry");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
    expect(requestBody(init)).toEqual({ event: "phase", phase: "listening", detail: "" });
  });

  it("keeps the detail short and never throws on a failing network", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    expect(() => reportTelemetry("send_failed", "thinking", "x".repeat(500))).not.toThrow();

    const body = requestBody(requestAt(0).init);
    expect(String(body.detail).length).toBeLessThan(200);
    // The rejection must be swallowed instead of surfacing as an unhandled one.
    await Promise.resolve();
  });

  it("swallows a synchronous fetch failure", () => {
    fetchMock.mockImplementationOnce(() => {
      throw new Error("boom");
    });
    expect(() => reportTelemetry("barge_in", "speaking", "speech")).not.toThrow();
  });
});
