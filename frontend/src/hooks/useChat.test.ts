import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionToken } from "../lib/api";
import type { ChatEntry, ChatReply } from "../types";
import { useChat, type ChatTurnResult } from "./useChat";

type AssistantEntry = Extract<ChatEntry, { role: "assistant" }>;

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function findAssistant(entries: ChatEntry[], id?: string): AssistantEntry | undefined {
  return entries.find(
    (entry): entry is AssistantEntry =>
      entry.role === "assistant" && (id === undefined || entry.id === id),
  );
}

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
}

const REPLY: ChatReply = {
  reply: "Создал задачу «Купить билеты».",
  audio: null,
  audio_mime: null,
  events: [],
  needs_clarification: false,
  intent: "create_task",
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

describe("useChat.sendText", () => {
  it("renders the reply text before the separately fetched speech is attached", async () => {
    let resolveChat: (response: Response) => void = () => {};
    let resolveSpeech: (response: Response) => void = () => {};
    fetchMock.mockImplementation((input) => {
      const path = String(input);
      if (path === "/api/chat") {
        return new Promise<Response>((resolve) => {
          resolveChat = resolve;
        });
      }
      if (path === "/api/speech") {
        return new Promise<Response>((resolve) => {
          resolveSpeech = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected request ${path}`));
    });

    const { result } = renderHook(() => useChat());
    let turn!: Promise<ChatTurnResult>;
    await act(async () => {
      turn = result.current.sendText("поставь задачу", { speak: true, voice: "v1" });
    });

    expect(result.current.pending).toBe(true);
    expect(result.current.entries.map((entry) => entry.role)).toEqual(["user"]);

    // /api/chat answers: the text has to be on screen right away.
    await act(async () => {
      resolveChat(jsonResponse(REPLY));
      await flush();
    });

    const assistant = findAssistant(result.current.entries);
    expect(assistant).toBeDefined();
    expect(assistant?.reply.reply).toBe(REPLY.reply);
    expect(assistant?.audio).toBeUndefined();
    // Sends stay serialised until the turn (including its voice) is done.
    expect(result.current.pending).toBe(true);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("/api/speech");
    const speechBody = JSON.parse(
      String(fetchMock.mock.calls[1]?.[1]?.body),
    ) as Record<string, unknown>;
    // The assistant answer is synthesised, not the user's phrase.
    expect(speechBody.text).toBe(REPLY.reply);
    expect(speechBody.voice).toBe("v1");

    // The speech arrives later and lands on the entry that is already rendered.
    await act(async () => {
      resolveSpeech(jsonResponse({ audio: "QUJD", audio_mime: "audio/ogg", audio_format: "opus" }));
      await flush();
    });

    const finished = await turn;
    expect(finished.hasAudio).toBe(true);
    expect(findAssistant(result.current.entries, assistant?.id)?.audio).toEqual({
      data: "QUJD",
      mime: "audio/ogg",
    });
  });

  it("never requests speech when speak-off mode is on", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    const { result } = renderHook(() => useChat());

    let turn!: Promise<ChatTurnResult>;
    await act(async () => {
      turn = result.current.sendText("Привет", { speak: false, voice: "v1" });
    });

    const finished = await turn;
    expect(finished.hasAudio).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/chat");
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as Record<string, unknown>;
    expect(body.speak).toBe(false);
    expect(findAssistant(result.current.entries)?.audio).toBeUndefined();
  });

  it("keeps the rendered reply when speech synthesis fails", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(REPLY))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const onSpeechError = vi.fn();
    const { result } = renderHook(() => useChat());

    let turn!: Promise<ChatTurnResult>;
    await act(async () => {
      turn = result.current.sendText("Привет", { speak: true, onSpeechError });
    });

    const finished = await turn;
    expect(finished.hasAudio).toBe(false);
    expect(finished.error).toBeNull();
    expect(onSpeechError).toHaveBeenCalledTimes(1);
    expect(findAssistant(result.current.entries)?.reply.reply).toBe(REPLY.reply);
    expect(result.current.entries.some((entry) => entry.role === "error")).toBe(false);
  });

  it("returns the inline audio instead of asking for speech", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...REPLY, audio: "QUJD", audio_mime: "audio/ogg" }),
    );
    const { result } = renderHook(() => useChat());

    let turn!: Promise<ChatTurnResult>;
    await act(async () => {
      turn = result.current.sendText("Привет", { speak: true });
    });

    const finished = await turn;
    expect(finished.hasAudio).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("useChat.attachAudio", () => {
  it("attaches audio to the matching assistant entry after the text rendered", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendText("Привет");
    });
    const assistant = findAssistant(result.current.entries);
    expect(assistant).toBeDefined();
    expect(assistant?.audio).toBeUndefined();

    act(() => {
      result.current.attachAudio(assistant!.id, "QUJD", "audio/ogg");
    });

    expect(findAssistant(result.current.entries, assistant!.id)?.audio).toEqual({
      data: "QUJD",
      mime: "audio/ogg",
    });
  });

  it("ignores empty payloads and unknown entry ids", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REPLY));
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendText("Привет");
    });
    const assistant = findAssistant(result.current.entries)!;

    act(() => {
      result.current.attachAudio(assistant.id, "", "audio/ogg");
      result.current.attachAudio("unknown", "AAA", null);
    });

    expect(findAssistant(result.current.entries, assistant.id)?.audio).toBeUndefined();
    expect(findAssistant(result.current.entries)?.reply.reply).toBe(REPLY.reply);
  });
});
