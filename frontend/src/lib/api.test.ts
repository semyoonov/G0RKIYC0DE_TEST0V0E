import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatReply } from "../types";
import {
  clearSessionToken,
  postChat,
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
  it("omits closing when it is false", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));

    await postChat("Привет", "client-anon", false);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestAt(0).path).toBe("/api/chat");
    const body = requestBody(requestAt(0).init);
    expect(body).toEqual({ text: "Привет", client_id: "client-anon", speak: false });
    expect("closing" in body).toBe(false);
  });

  it("sends closing true for a farewell", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));

    await postChat("Спасибо", "client-anon", true, true);

    expect(requestBody(requestAt(0).init)).toEqual({
      text: "Спасибо",
      client_id: "client-anon",
      speak: true,
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
    await postChat("Что на завтра?", "client-1", true, false, "Gli-Operator");
    expect(requestBody(requestAt(0).init)).toMatchObject({ voice: "Gli-Operator" });

    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    await postChat("Что на завтра?", "client-1", true, false, "");
    expect(requestBody(requestAt(1).init)).not.toHaveProperty("voice");
  });
});
