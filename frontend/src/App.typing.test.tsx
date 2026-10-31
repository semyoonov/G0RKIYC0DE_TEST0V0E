import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { bootstrapSession } from "./lib/session";

const ANSWER = "Создал задачу «Купить билеты».";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function guestSession() {
  return {
    token: "app-token",
    identity: { platform: "web", platform_title: "Веб", external_id: "guest-1", display_name: null },
    user: { id: 1 },
    linked: [],
    mini_apps: { telegram: null, max: null, vk: null, web: "https://example.test/" },
    email: null,
    has_password: false,
  };
}

let replyChat: (response: Response) => void = () => {};

beforeEach(() => {
  window.localStorage.clear();
  // Без озвучки: проверяем только текстовый ответ.
  window.localStorage.setItem("assistant.speakReplies", "0");
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      if (String(input) === "/api/auth/guest" || String(input) === "/api/auth/me") {
        return Promise.resolve(json(guestSession()));
      }
      if (String(input) === "/api/chat") {
        return new Promise<Response>((resolve) => {
          replyChat = resolve;
        });
      }
      return Promise.resolve(json({}, 500));
    }),
  );
});

beforeEach(async () => {
  await bootstrapSession();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function send(text: string) {
  const user = userEvent.setup();
  // Приложение сначала открывает гостевую сессию, и только потом поле готово.
  await waitFor(() => expect(screen.getByLabelText("Сообщение")).toBeEnabled());
  await user.type(screen.getByLabelText("Сообщение"), text);
  await user.click(screen.getByRole("button", { name: "Отправить" }));
}

describe("пока ассистент отвечает", () => {
  it("в чате «Отвечаю», а не «Обрабатываю» внизу; потом на его месте появляется ответ", async () => {
    render(<App />);
    await send("Купить билеты завтра");

    expect(await screen.findByText("Отвечаю")).toBeInTheDocument();
    expect(screen.queryByText(/Обрабатываю/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    replyChat(
      json({
        reply: ANSWER,
        audio: null,
        audio_mime: null,
        events: [],
        needs_clarification: false,
        intent: null,
      }),
    );

    expect(await screen.findByText(ANSWER)).toBeInTheDocument();
    expect(screen.queryByText("Отвечаю")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).not.toBeEmptyDOMElement();
  });

  it("при ошибке «Отвечаю» пропадает и вместо ответа видна ошибка", async () => {
    render(<App />);
    await send("Купить билеты завтра");
    await screen.findByText("Отвечаю");

    replyChat(json({ detail: "Сервис недоступен" }, 503));

    await waitFor(() => expect(screen.queryByText("Отвечаю")).not.toBeInTheDocument());
    expect(screen.getAllByText(/недоступен/i).length).toBeGreaterThan(0);
  });
});
