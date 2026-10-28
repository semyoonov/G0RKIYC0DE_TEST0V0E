import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NETWORK_ERROR_TEXT } from "../lib/api";
import * as session from "../lib/session";
import type { AuthSession, LinkCodeResponse, MiniApps } from "../types";
import { LinkPanel } from "./LinkPanel";

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
  telegram: "https://t.me/assistant_bot?startapp=CODE",
  vk: null,
  max: null,
  web: "https://example.test/?start=CODE",
};

const CODE_RESPONSE: LinkCodeResponse = {
  code: "AB12CD",
  expires_at: "2025-01-01T00:10:00Z",
  expires_in: 600,
  platform: "web",
  mini_apps: {
    telegram: "https://t.me/assistant_bot?startapp=AB12CD",
    vk: null,
    max: null,
    web: "https://example.test/?start=AB12CD",
  },
  web_link: "https://example.test/?start=AB12CD",
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

describe("LinkPanel", () => {
  it("requests a code and links another platform", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(makeSession()))
      .mockResolvedValueOnce(jsonResponse(CODE_RESPONSE))
      .mockResolvedValueOnce(
        jsonResponse(
          makeSession({
            token: "panel-token-2",
            link_redeemed: true,
            linked: [
              {
                platform: "web",
                platform_title: "Веб",
                external_id: "client-panel",
                display_name: "Александр",
              },
              {
                platform: "telegram",
                platform_title: "Telegram",
                external_id: "42",
                display_name: "@durov",
              },
            ],
          }),
        ),
      );

    await session.bootstrapSession();
    render(<LinkPanel />);

    await user.click(screen.getByRole("button", { name: /Веб/ }));
    expect(screen.getByText("Привязанные аккаунты")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Получить код" }));

    expect(await screen.findByText("AB12CD")).toBeInTheDocument();
    expect(screen.getByText("Действует 10 мин.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Telegram/ })).toHaveAttribute(
      "href",
      "https://t.me/assistant_bot?startapp=AB12CD",
    );
    expect(screen.getByRole("link", { name: /Веб-ссылка/ })).toHaveAttribute(
      "href",
      "https://example.test/?start=AB12CD",
    );
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/auth/code");
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("POST");
    expect(new Headers(fetchMock.mock.calls[1]?.[1]?.headers).get("Authorization")).toBe(
      "Bearer panel-token",
    );

    await user.type(screen.getByLabelText("Код привязки"), "AB12CD");
    await user.click(screen.getByRole("button", { name: "Привязать" }));

    expect(await screen.findByText("Аккаунт привязан.")).toBeInTheDocument();
    expect(screen.getByText("@durov")).toBeInTheDocument();
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/auth/link");
    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe("POST");
    expect(JSON.parse(String(fetchMock.mock.calls[2]?.[1]?.body))).toEqual({ code: "AB12CD" });
    expect(new Headers(fetchMock.mock.calls[2]?.[1]?.headers).get("Authorization")).toBe(
      "Bearer panel-token",
    );
    expect(session.getSessionSnapshot().linkRedeemed).toBe(false);
    expect(session.getToken()).toBe("panel-token-2");
  });

  it("shows a readable error when the session cannot start", async () => {
    const user = userEvent.setup();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await session.bootstrapSession();
    render(<LinkPanel />);

    await user.click(screen.getByRole("button", { name: /Вход в аккаунт/ }));

    expect(screen.getByRole("alert")).toHaveTextContent(NETWORK_ERROR_TEXT);
    expect(screen.getByRole("button", { name: "Повторить вход" })).toBeInTheDocument();
  });
});
