import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { clearSpeechCache } from "./lib/api";
import { bootstrapSession } from "./lib/session";

// The microphone is replaced by a controllable stub: jsdom has no audio capture,
// and the one-shot path must end with an audio blob, like browsers without streaming.
vi.mock("./hooks/useVoiceStream", async () => {
  const { useMemo, useState } = await import("react");
  return {
    useVoiceStream: () => {
      const [recording, setRecording] = useState(false);
      const actions = useMemo(
        () => ({
          start: async () => setRecording(true),
          stop: async () => {
            setRecording(false);
            return { kind: "blob" as const, blob: new Blob(["mic"], { type: "audio/webm" }) };
          },
          clearError: () => {},
          openMicrophone: async () => false,
          beginTurn: async () => false,
          commitTurn: async () => ({ kind: "empty" as const }),
          releaseMicrophone: () => {},
          mute: () => {},
          unmute: () => {},
          subscribeEnergy: () => () => {},
        }),
        [],
      );
      return { recording, busy: false, partial: "", error: null, streaming: false, ...actions };
    },
  };
});

const CATALOGUE = ["Mer-Operator", "Kaz-Lifelike", "Gli-Operator", "Bab-Debate", "Bab-Energetic"];
const ANSWER = "Сегодня в 10:00 встреча с командой.";

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

interface Call {
  url: string;
  init: RequestInit | undefined;
}

let calls: Call[] = [];
let metaHandler: () => Promise<Response>;
let speechHandler: (init: RequestInit | undefined) => Promise<Response>;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function chatReply(audio: string | null = null) {
  return {
    reply: ANSWER,
    audio,
    audio_mime: audio ? "audio/ogg" : null,
    events: [],
    needs_clarification: false,
    intent: null,
  };
}

function meta(overrides: Record<string, unknown> = {}) {
  return json({
    timezone: "Europe/Moscow",
    quick_actions: ["Что у меня сегодня?", "Что на завтра?"],
    mini_apps: { telegram: null, max: null, vk: null, web: null },
    platforms: ["web"],
    voices: CATALOGUE,
    voice: "Mer-Operator",
    ...overrides,
  });
}

function bodiesOf(url: string): Array<Record<string, unknown>> {
  return calls
    .filter((call) => call.url === url)
    .map((call) => JSON.parse(String(call.init?.body)) as Record<string, unknown>);
}

/** The voice the server will actually use: an omitted field means its own default. */
function requestedVoice(body: Record<string, unknown> | undefined): string {
  return typeof body?.voice === "string" ? body.voice : "<голос сервера по умолчанию>";
}

function voicePicker(): HTMLSelectElement {
  return screen.getByLabelText("Голос озвучки") as HTMLSelectElement;
}

async function waitForCatalogue() {
  await waitFor(() => expect(within(voicePicker()).getAllByRole("option")).toHaveLength(CATALOGUE.length));
}

async function askToday(user: ReturnType<typeof userEvent.setup>) {
  const button = screen.getByRole("button", { name: "Что у меня сегодня?" });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
}

beforeEach(() => {
  calls = [];
  window.localStorage.clear();
  clearSpeechCache();
  metaHandler = async () => meta();
  speechHandler = async (init) => {
    const body = JSON.parse(String(init?.body)) as { voice?: string };
    return json({ audio: window.btoa(`voice=${body.voice ?? "default"}`), audio_mime: "audio/ogg" });
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url === "/api/auth/guest" || url === "/api/auth/me") return json(guestSession());
      if (url === "/api/meta") return metaHandler();
      if (url === "/api/chat") return json(chatReply());
      if (url === "/api/speech") return speechHandler(init);
      if (url === "/api/voice") return json(chatReply(window.btoa("voice=server-default")));
      return json({ ok: true });
    }),
  );
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(() => "blob:reply"),
  });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, writable: true, value: vi.fn() });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});

beforeEach(async () => {
  await bootstrapSession();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("выбранный голос — тот, что звучит", () => {
  it("синтезирует ответ именно выбранным голосом", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();

    await user.selectOptions(voicePicker(), "Bab-Debate");
    await askToday(user);

    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(1));
    expect(bodiesOf("/api/speech")[0]).toMatchObject({ text: ANSWER, voice: "Bab-Debate" });
    expect(await screen.findByRole("button", { name: "Прослушать ответ" })).toBeInTheDocument();
  });

  it("после смены голоса тот же ответ синтезируется заново, а не берётся из кэша старым голосом", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();

    await user.selectOptions(voicePicker(), "Gli-Operator");
    await askToday(user);
    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(1));

    await user.selectOptions(voicePicker(), "Bab-Debate");
    await askToday(user);

    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(2));
    expect(bodiesOf("/api/speech").map(requestedVoice)).toEqual(["Gli-Operator", "Bab-Debate"]);
  });

  it("выбор голоса переживает перезагрузку и не затирается голосом сервера", async () => {
    const user = userEvent.setup();
    const first = render(<App />);
    await waitForCatalogue();
    await user.selectOptions(voicePicker(), "Kaz-Lifelike");
    first.unmount();

    render(<App />);
    await waitForCatalogue();
    expect(voicePicker().value).toBe("Kaz-Lifelike");

    await askToday(user);
    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(1));
    expect(requestedVoice(bodiesOf("/api/speech")[0])).toBe("Kaz-Lifelike");
  });

  it("если сохранённого голоса больше нет в каталоге, звучит тот, что показан в списке", async () => {
    // Голос, выбранный раньше, убрали с сервера: список показывает первый из каталога.
    window.localStorage.setItem("assistant.ttsVoice", "Retired-Voice");
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();
    const shown = voicePicker().value;

    await askToday(user);
    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(1));
    expect(requestedVoice(bodiesOf("/api/speech")[0])).toBe(shown);
  });

  it("если спросить до прихода каталога, звучит тот голос, что уже показан в списке", async () => {
    // Сервер по умолчанию озвучивает не первым голосом списка (CLOUD_TTS_VOICE в .env).
    let releaseMeta: (response: Response) => void = () => {};
    metaHandler = () =>
      new Promise<Response>((resolve) => {
        releaseMeta = resolve;
      });
    const user = userEvent.setup();
    render(<App />);
    const shown = voicePicker().value;

    await askToday(user);
    await waitFor(() => expect(bodiesOf("/api/speech")).toHaveLength(1));
    releaseMeta(meta({ voice: "Kaz-Lifelike" }));
    expect(requestedVoice(bodiesOf("/api/speech")[0])).toBe(shown);
  });

  it("запись кнопкой «Голосом» без стриминга тоже отвечает выбранным голосом", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();
    await user.selectOptions(voicePicker(), "Bab-Debate");

    await user.click(screen.getByRole("button", { name: "Записать голосом" }));
    await user.click(await screen.findByRole("button", { name: "Остановить запись" }));

    await waitFor(() => expect(calls.some((call) => call.url === "/api/voice")).toBe(true));
    const form = calls.find((call) => call.url === "/api/voice")?.init?.body as FormData;
    expect(form.get("voice")).toBe("Bab-Debate");
  });
});

describe("режим «Текстом»", () => {
  it("блокирует выбор голоса и ни разу не просит синтез", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();

    await user.click(screen.getByRole("radio", { name: "Текстом" }));
    expect(voicePicker()).toBeDisabled();
    expect(window.localStorage.getItem("assistant.speakReplies")).toBe("0");

    await askToday(user);
    expect(await screen.findByText(ANSWER)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Что у меня сегодня?" })).toBeEnabled());
    expect(bodiesOf("/api/speech")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Прослушать ответ" })).not.toBeInTheDocument();
  });

  describe("переключение на «Текстом», пока ответ ещё озвучивается", () => {
    let speechStarted = false;
    let speechSignal: AbortSignal | null | undefined;
    let finishSpeech: () => void = () => {};

    beforeEach(() => {
      speechStarted = false;
      speechSignal = undefined;
      speechHandler = (init) =>
        new Promise<Response>((resolve, reject) => {
          speechStarted = true;
          speechSignal = init?.signal;
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
          finishSpeech = () => resolve(json({ audio: window.btoa("late"), audio_mime: "audio/ogg" }));
        });
    });

    it("опоздавший синтез уже не звучит", async () => {
      const user = userEvent.setup();
      render(<App />);
      await waitForCatalogue();

      await askToday(user);
      await waitFor(() => expect(speechStarted).toBe(true));
      await user.click(screen.getByRole("radio", { name: "Текстом" }));
      finishSpeech();

      await waitFor(() => expect(screen.getByRole("button", { name: "Что у меня сегодня?" })).toBeEnabled());
      expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    });

    it("и сам запрос синтеза отменяется, а не доделывается впустую", async () => {
      const user = userEvent.setup();
      render(<App />);
      await waitForCatalogue();

      await askToday(user);
      await waitFor(() => expect(speechStarted).toBe(true));
      await user.click(screen.getByRole("radio", { name: "Текстом" }));

      expect(speechSignal, "запрос /api/speech ушёл без сигнала отмены").toBeTruthy();
      expect(speechSignal?.aborted).toBe(true);
      finishSpeech();
    });
  });

  it("включённый обратно «Голосом» не проигрывает задним числом старые ответы", async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitForCatalogue();

    await askToday(user);
    await screen.findByRole("button", { name: "Прослушать ответ" });
    await user.click(screen.getByRole("radio", { name: "Текстом" }));
    const playsBefore = vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length;

    await user.click(screen.getByRole("radio", { name: "Голосом" }));
    expect(voicePicker()).toBeEnabled();
    expect(vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length).toBe(playsBefore);
  });
});
