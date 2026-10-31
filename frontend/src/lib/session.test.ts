import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthSession, ChatReply, MiniApps } from "../types";
import { NETWORK_ERROR_TEXT, postChat } from "./api";
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
  telegram: "https://t.me/assistant_bot",
  vk: null,
  max: null,
  web: "https://example.test/",
};

function makeSession(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    token: "token-1",
    identity: {
      platform: "web",
      platform_title: "Веб",
      external_id: "email-identity-1",
      display_name: null,
    },
    user: { id: 7 },
    linked: [
      {
        platform: "web",
        platform_title: "Веб",
        external_id: "email-identity-1",
        display_name: null,
      },
    ],
    mini_apps: MINI_APPS,
    email: null,
    has_password: false,
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
  it("opens a guest session instead of asking for a login", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(makeSession({ token: "guest-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestAt(0).path).toBe("/api/auth/guest");
    expect(requestAt(0).init?.method).toBe("POST");
    expect(window.localStorage.getItem("assistant_session_token")).toBe("guest-token");
    expect(session.getSessionSnapshot().status).toBe("ready");
    expect(session.getSessionSnapshot().session?.email).toBeNull();
  });

  it("reuses a stored token through /api/auth/me", async () => {
    window.localStorage.setItem("assistant_session_token", "stored-token");
    fetchMock.mockResolvedValueOnce(jsonResponse(makeSession({ token: "refreshed-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestAt(0).path).toBe("/api/auth/me");
    expect(authorization(requestAt(0).init)).toBe("Bearer stored-token");
    expect(window.localStorage.getItem("assistant_session_token")).toBe("refreshed-token");
    expect(session.getToken()).toBe("refreshed-token");
    expect(session.getSessionSnapshot().status).toBe("ready");
  });

  it("prefers a signed mini-app launch over a stored web token", async () => {
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
    expect(requestAt(0).path).toBe("/api/auth/session");
    expect(requestBody(requestAt(0).init)).toEqual({ platform: "vk", payload: "vk_user_id=1&sign=abc" });
    expect(window.localStorage.getItem("assistant_session_token")).toBe("vk-token");
    expect(session.getSessionSnapshot().session?.identity.platform).toBe("vk");
  });

  it("replaces an expired token with a guest session", async () => {
    window.localStorage.setItem("assistant_session_token", "legacy-token");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Сессия истекла." }, 401))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "guest-token" })));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(requestAt(0).path).toBe("/api/auth/me");
    expect(requestAt(1).path).toBe("/api/auth/guest");
    expect(window.localStorage.getItem("assistant_session_token")).toBe("guest-token");
    expect(session.getSessionSnapshot().status).toBe("ready");
  });

  it("does not fall back to anonymous web login when mini-app auth fails", async () => {
    launchState.current = { platform: "telegram", payload: "auth_date=1&hash=abc" };
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Этот способ входа пока не настроен." }, 503));

    await session.bootstrapSession();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(requestBody(requestAt(0).init)).toEqual({
      platform: "telegram",
      payload: "auth_date=1&hash=abc",
    });
    const snapshot = session.getSessionSnapshot();
    expect(snapshot.status).toBe("error");
    expect(snapshot.session).toBeNull();
    expect(snapshot.fallback?.platform).toBe("telegram");
  });

  it("reports a readable error when the server is unreachable", async () => {
    window.localStorage.setItem("assistant_session_token", "stored-token");
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(session.bootstrapSession()).resolves.toBeUndefined();

    const snapshot = session.getSessionSnapshot();
    expect(snapshot.status).toBe("error");
    expect(snapshot.error).toBe(NETWORK_ERROR_TEXT);
    expect(snapshot.session).toBeNull();
    // Токен остаётся: следующая загрузка повторит попытку, а не начнёт заново.
    expect(session.getToken()).toBe("stored-token");
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

  it("retries an unauthorized chat request once with a guest session", async () => {
    window.localStorage.setItem("assistant_session_token", "legacy-token");
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "Нет доступа." }, 401))
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "guest-token" })))
      .mockResolvedValueOnce(jsonResponse(reply));

    await expect(postChat("Привет")).resolves.toEqual(reply);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(requestAt(0).path).toBe("/api/chat");
    expect(authorization(requestAt(0).init)).toBe("Bearer legacy-token");
    expect(requestAt(1).path).toBe("/api/auth/guest");
    expect(authorization(requestAt(2).init)).toBe("Bearer guest-token");
    expect(session.getSessionSnapshot().status).toBe("ready");
  });

  it("does not send client_id with an authenticated chat request", async () => {
    window.localStorage.setItem("assistant_session_token", "valid-token");
    fetchMock.mockResolvedValueOnce(jsonResponse(reply));

    await expect(postChat("Привет")).resolves.toEqual(reply);

    expect(requestBody(requestAt(0).init)).toEqual({ text: "Привет", speak: false });
  });
});
