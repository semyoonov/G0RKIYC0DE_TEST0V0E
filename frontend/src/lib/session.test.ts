import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthSession, ChatReply, MiniApps } from "../types";
import { ApiError, NETWORK_ERROR_TEXT, postChat } from "./api";
import * as session from "./session";

const launchState = vi.hoisted(() => ({
  current: {
    platform: "web" as "telegram" | "max" | "vk" | "web",
    payload: null as string | null,
  },
}));

vi.mock("./platform", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./platform")>();
  return { ...actual, detectLaunch: () => launchState.current };
});

const MINI_APPS: MiniApps = {
  telegram: "https://t.me/assistant_bot?startapp=CODE",
  vk: null,
  max: null,
  web: "https://example.test/?start=CODE",
};

function makeSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    token: "token-1",
    identity: {
      platform: "web",
      platform_title: "Веб",
      external_id: "client-anon",
      display_name: null,
    },
    user: { id: 7 },
    linked: [
      {
        platform: "web",
        platform_title: "Веб",
        external_id: "client-anon",
        display_name: null,
      },
    ],
    start_param: null,
    link_redeemed: false,
    mini_apps: MINI_APPS,
    ...overrides,
  };
}

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

function authorization(init: RequestInit | undefined): string | null {
  return new Headers(init?.headers).get("Authorization");
}

function requestBody(init: RequestInit | undefined): Record<string, unknown> {
  return JSON.parse(String(init?.body)) as Record<string, unknown>;
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  session.resetSession();
  window.localStorage.clear();
  launchState.current = { platform: "web", payload: null };
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("bootstrapSession", () => {
  it("opens a web session with the anonymous client id", async () => {
    window.localStorage.setItem("assistant_client_id", "client-anon");
    fetchMock.mockResolvedValueOnce(jsonResponse(makeSession()));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/auth/session");
    expect(init?.method).toBe("POST");
    expect(requestBody(init)).toEqual({
      platform: "web",
      payload: null,
      client_id: "client-anon",
    });
    expect(window.localStorage.getItem("assistant_session_token")).toBe("token-1");
    expect(session.getToken()).toBe("token-1");
    const snapshot = session.getSessionSnapshot();
    expect(snapshot.status).toBe("ready");
    expect(snapshot.session?.identity.platform).toBe("web");
    expect(snapshot.error).toBeNull();
    expect(snapshot.fallback).toBeNull();
  });

  it("reuses a stored token through /api/auth/me", async () => {
    window.localStorage.setItem("assistant_session_token", "stored-token");
    fetchMock.mockResolvedValueOnce(jsonResponse(makeSession({ token: "refreshed-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/auth/me");
    expect(authorization(init)).toBe("Bearer stored-token");
    expect(window.localStorage.getItem("assistant_session_token")).toBe("refreshed-token");
    expect(session.getToken()).toBe("refreshed-token");
    expect(session.getSessionSnapshot().status).toBe("ready");
  });

  it("prefers the mini app launch over a stored web token", async () => {
    launchState.current = { platform: "vk", payload: "vk_user_id=1&sign=abc" };
    window.localStorage.setItem("assistant_session_token", "web-token");
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeSession({
          token: "vk-token",
          identity: {
            platform: "vk",
            platform_title: "ВКонтакте",
            external_id: "1",
            display_name: "Иван Петров",
          },
        }),
      ),
    );

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const { path, init } = requestAt(0);
    expect(path).toBe("/api/auth/session");
    expect(requestBody(init)).toEqual({ platform: "vk", payload: "vk_user_id=1&sign=abc", client_id: null });
    expect(window.localStorage.getItem("assistant_session_token")).toBe("vk-token");
    expect(session.getSessionSnapshot().session?.identity.platform).toBe("vk");
  });

  it("opens a fresh session when the stored token is rejected", async () => {
    window.localStorage.setItem("assistant_session_token", "stale-token");
    window.localStorage.setItem("assistant_client_id", "client-anon");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Сессия истекла. Обновите страницу." }, 401))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "fresh-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestAt(0).path).toBe("/api/auth/me");
    expect(requestAt(1).path).toBe("/api/auth/session");
    expect(requestBody(requestAt(1).init)).toMatchObject({
      platform: "web",
      client_id: "client-anon",
    });
    expect(window.localStorage.getItem("assistant_session_token")).toBe("fresh-token");
    expect(session.getSessionSnapshot().error).toBeNull();
  });

  it("falls back to the web login when the platform is unavailable", async () => {
    launchState.current = { platform: "telegram", payload: "auth_date=1&hash=abc" };
    window.localStorage.setItem("assistant_client_id", "client-anon");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Этот способ входа пока не настроен." }, 503))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "web-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestBody(requestAt(0).init)).toEqual({
      platform: "telegram",
      payload: "auth_date=1&hash=abc",
      client_id: null,
    });
    expect(requestBody(requestAt(1).init)).toEqual({
      platform: "web",
      payload: null,
      client_id: "client-anon",
    });
    const snapshot = session.getSessionSnapshot();
    expect(snapshot.status).toBe("ready");
    expect(snapshot.fallback).toEqual({
      platform: "telegram",
      reason: "Этот способ входа пока не настроен.",
    });
    expect(snapshot.session?.identity.platform).toBe("web");
    expect(session.getToken()).toBe("web-token");
  });

  it("reports a readable error when the server is unreachable", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(session.bootstrapSession()).resolves.toBeUndefined();

    const snapshot = session.getSessionSnapshot();
    expect(snapshot.status).toBe("error");
    expect(snapshot.error).toBe(NETWORK_ERROR_TEXT);
    expect(snapshot.session).toBeNull();
    expect(session.getToken()).toBeNull();
  });
});

describe("account requests", () => {
  const reply: ChatReply = {
    reply: "Готово",
    audio: null,
    audio_mime: null,
    events: [],
    needs_clarification: false,
    intent: null,
  };

  it("retries once with a fresh token after a 401", async () => {
    window.localStorage.setItem("assistant_session_token", "stale-token");
    window.localStorage.setItem("assistant_client_id", "client-anon");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Сессия истекла." }, 401))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "fresh-token" })))
      .mockResolvedValueOnce(jsonResponse(reply));

    const result = await postChat("Привет", "client-anon");

    expect(result).toEqual(reply);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(requestAt(0).path).toBe("/api/chat");
    expect(authorization(requestAt(0).init)).toBe("Bearer stale-token");
    expect(requestAt(1).path).toBe("/api/auth/session");
    expect(requestAt(2).path).toBe("/api/chat");
    expect(authorization(requestAt(2).init)).toBe("Bearer fresh-token");
    expect(window.localStorage.getItem("assistant_session_token")).toBe("fresh-token");
    expect(session.getToken()).toBe("fresh-token");
  });

  it("does not retry a second 401", async () => {
    window.localStorage.setItem("assistant_session_token", "stale-token");
    window.localStorage.setItem("assistant_client_id", "client-anon");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Сессия истекла." }, 401))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "fresh-token" })))
      .mockResolvedValueOnce(jsonResponse({ detail: "Нет доступа." }, 401));

    await expect(postChat("Привет", "client-anon")).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
