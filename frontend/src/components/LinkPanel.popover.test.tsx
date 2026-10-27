import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as session from "../lib/session";
import { LinkPanel } from "./LinkPanel";

function renderInPage() {
  render(
    <div>
      <button type="button">Чат</button>
      <LinkPanel />
    </div>,
  );
  return screen.getByRole("button", { name: /Аккаунт и настройки/ });
}

beforeEach(() => {
  session.resetSession();
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("LinkPanel как всплывающее окно", () => {
  it("закрывается кликом мимо окна", async () => {
    const user = userEvent.setup();
    const trigger = renderInPage();

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Аккаунт и привязка" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Чат" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("закрывается по Esc и возвращает фокус на шестерёнку", async () => {
    const user = userEvent.setup();
    const trigger = renderInPage();

    await user.click(trigger);
    await user.click(screen.getByLabelText("Код привязки"));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("не закрывается от кликов и ввода внутри окна", async () => {
    // С живой сессией поле кода доступно для ввода.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            token: "popover-token",
            identity: { platform: "web", platform_title: "Веб", external_id: "c1", display_name: null },
            user: { id: 1 },
            linked: [],
            start_param: null,
            link_redeemed: false,
            mini_apps: { telegram: null, max: null, vk: null, web: null },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    await session.bootstrapSession();
    const user = userEvent.setup();
    const trigger = renderInPage();

    await user.click(trigger);
    await user.click(screen.getByText("Привязанные аккаунты"));
    await user.type(screen.getByLabelText("Код привязки"), "AB12");

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Код привязки")).toHaveValue("AB12");
  });

  it("повторный клик по шестерёнке закрывает окно, а не открывает его заново", async () => {
    const user = userEvent.setup();
    const trigger = renderInPage();

    await user.click(trigger);
    await user.click(trigger);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("закрытое окно не реагирует на Esc и клики по странице", async () => {
    const user = userEvent.setup();
    const trigger = renderInPage();

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Чат" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).not.toHaveFocus();
  });
});
