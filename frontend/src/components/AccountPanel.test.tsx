import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NETWORK_ERROR_TEXT } from "../lib/api";
import * as session from "../lib/session";
import type { AuthSession, MiniApps } from "../types";
import { AccountPanel } from "./AccountPanel";

const launchState = vi.hoisted(() => ({
  current: {
    platform: "web" as "telegram" | "max" | "vk" | "web",
    payload: null as string | null,
  },
}));

vi.mock("../lib/platform", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/platform")>();
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
    token: "panel-token",
    identity: {
      platform: "web",
      platform_title: "Веб",
      external_id: "client-panel",
      display_name: "Александр",
    },
    user: { id: 7 },
    linked: [
      {
        platform: "web",
        platform_title: "Веб",
        external_id: "client-panel",
        display_name: "Александр",
      },
    ],
    mini_apps: MINI_APPS,
    email: "user@example.com",
    has_password: true,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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
  cleanup();
  vi.unstubAllGlobals();
});

describe("AccountPanel", () => {
  it("lists the platforms already attached to the account", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        makeSession({
          linked: [
            { platform: "web", platform_title: "Веб", external_id: "email-1", display_name: null },
            { platform: "telegram", platform_title: "Telegram", external_id: "42", display_name: "@durov" },
          ],
        }),
      ),
    );

    await session.bootstrapSession();
    render(<AccountPanel />);

    await user.click(screen.getByRole("button", { name: /Веб/ }));

    expect(await screen.findByText("Привязанные аккаунты")).toBeInTheDocument();
    expect(screen.getByText("Вход по почте")).toBeInTheDocument();
    expect(screen.getByText("@durov")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Выйти" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Электронная почта")).not.toBeInTheDocument();
  });

  it("shows a readable error when the session cannot start", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("assistant_session_token", "stored-token");
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await session.bootstrapSession();
    render(<AccountPanel />);

    await user.click(screen.getByRole("button", { name: /Аккаунт/ }));

    expect(screen.getByRole("alert")).toHaveTextContent(NETWORK_ERROR_TEXT);
    expect(screen.getByRole("button", { name: "Повторить" })).toBeInTheDocument();
  });

  it("registers a guest account with a password and keeps its session", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(makeSession({ token: "guest-token", email: null, has_password: false })))
      .mockResolvedValueOnce(
        jsonResponse(makeSession({ token: "account-token", email: "me@example.com" })),
      );

    await session.bootstrapSession();
    render(<AccountPanel />);

    await user.click(screen.getByRole("button", { name: /Веб/ }));
    await user.type(screen.getByLabelText("Электронная почта"), "me@example.com");
    await user.type(screen.getByLabelText("Пароль"), "long-password");
    await user.click(screen.getByRole("button", { name: "Зарегистрироваться" }));

    expect(await screen.findByText("me@example.com")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/register");
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({
      email: "me@example.com",
      password: "long-password",
    });
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("Authorization")).toBe(
      "Bearer guest-token",
    );
    expect(session.getToken()).toBe("account-token");
  });
});
