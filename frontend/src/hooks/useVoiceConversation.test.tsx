import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VoiceTurnOutcome } from "../lib/conversation";
import type { VoiceController } from "./useVoiceStream";
import { useVoiceConversation } from "./useVoiceConversation";

interface FakeVoice {
  voice: VoiceController;
  emit: (energy: number) => void;
}

function makeFakeVoice(): FakeVoice {
  const handlers = new Set<(energy: number) => void>();
  const voice: VoiceController = {
    recording: true,
    busy: false,
    partial: "",
    error: null,
    streaming: true,
    start: vi.fn(async () => {}),
    stop: vi.fn(async () => null),
    clearError: vi.fn(),
    openMicrophone: vi.fn(async () => true),
    beginTurn: vi.fn(async () => true),
    commitTurn: vi.fn(async (): Promise<VoiceTurnOutcome> => ({
      kind: "text",
      text: "поставь задачу",
    })),
    releaseMicrophone: vi.fn(),
    subscribeEnergy: (handler: (energy: number) => void) => {
      handlers.add(handler);
      return () => {
        handlers.delete(handler);
      };
    },
  };
  return {
    voice,
    emit: (energy: number) => handlers.forEach((handler) => handler(energy)),
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("useVoiceConversation auto-commit", () => {
  it("commits after speech, silence and an existing partial", async () => {
    vi.useFakeTimers();
    const fake = makeFakeVoice();
    const sendUtterance = vi.fn(async () => ({ ok: true, hasAudio: false }));
    const props = {
      voice: fake.voice,
      sendUtterance,
      reportError: vi.fn(),
    };
    const { result, rerender, unmount } = renderHook(
      (current: typeof props) => useVoiceConversation(current),
      { initialProps: props },
    );

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.active).toBe(true);
    expect(result.current.phase).toBe("listening");
    expect(fake.voice.beginTurn).toHaveBeenCalledTimes(1);

    act(() => {
      fake.emit(0.08);
    });
    rerender({
      ...props,
      voice: { ...fake.voice, partial: "поставь задачу" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_499);
    });
    expect(fake.voice.commitTurn).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(fake.voice.commitTurn).toHaveBeenCalledTimes(1);
    expect(sendUtterance).toHaveBeenCalledWith("поставь задачу", { closing: false });

    unmount();
  });

  it("commits as soon as the recognizer clears its own partial", async () => {
    const fake = makeFakeVoice();
    const sendUtterance = vi.fn(async () => ({ ok: true, hasAudio: false }));
    const props = {
      voice: fake.voice,
      sendUtterance,
      reportError: vi.fn(),
    };
    const { result, rerender, unmount } = renderHook(
      (current: typeof props) => useVoiceConversation(current),
      { initialProps: props },
    );

    await act(async () => {
      await result.current.start();
    });
    act(() => {
      fake.emit(0.08);
    });
    rerender({ ...props, voice: { ...fake.voice, partial: "что у меня на завтра" } });
    expect(fake.voice.commitTurn).not.toHaveBeenCalled();

    await act(async () => {
      rerender({ ...props, voice: { ...fake.voice, partial: "" } });
    });

    expect(fake.voice.commitTurn).toHaveBeenCalledTimes(1);
    expect(sendUtterance).toHaveBeenCalledWith("поставь задачу", { closing: false });
    unmount();
  });

  it("does not commit a silent turn even with a partial transcript", async () => {
    vi.useFakeTimers();
    const fake = makeFakeVoice();
    const sendUtterance = vi.fn(async () => ({ ok: true, hasAudio: false }));
    const props = {
      voice: fake.voice,
      sendUtterance,
      reportError: vi.fn(),
    };
    const { result, rerender, unmount } = renderHook(
      (current: typeof props) => useVoiceConversation(current),
      { initialProps: props },
    );

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.active).toBe(true);

    act(() => {
      for (let index = 0; index < 100; index += 1) fake.emit(0.002);
    });
    rerender({
      ...props,
      voice: { ...fake.voice, partial: "посторонний шум" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    expect(fake.voice.commitTurn).not.toHaveBeenCalled();
    expect(sendUtterance).not.toHaveBeenCalled();
    expect(result.current.active).toBe(true);
    expect(result.current.phase).toBe("listening");

    unmount();
  });

  it("leaves the mode when the voice layer reports an error", async () => {
    const fake = makeFakeVoice();
    const props = {
      voice: fake.voice,
      sendUtterance: vi.fn(async () => ({ ok: true, hasAudio: false })),
      reportError: vi.fn(),
    };
    const { result, rerender, unmount } = renderHook(
      (current: typeof props) => useVoiceConversation(current),
      { initialProps: props },
    );

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.active).toBe(true);

    rerender({
      ...props,
      voice: { ...fake.voice, error: "Не удалось включить микрофон." },
    });
    await act(async () => {
      for (let index = 0; index < 12; index += 1) await Promise.resolve();
    });

    expect(result.current.active).toBe(false);
    expect(result.current.phase).toBe("idle");
    expect(fake.voice.releaseMicrophone).toHaveBeenCalled();

    unmount();
  });

  it("fires a best-effort warmup whenever the mode is entered", async () => {
    const fake = makeFakeVoice();
    const warmup = vi.fn();
    const { result, unmount } = renderHook(() =>
      useVoiceConversation({
        voice: fake.voice,
        sendUtterance: vi.fn(async () => ({ ok: true, hasAudio: false })),
        reportError: vi.fn(),
        warmup,
      }),
    );

    await act(async () => {
      await result.current.start();
    });

    expect(warmup).toHaveBeenCalledTimes(1);
    expect(result.current.active).toBe(true);
    expect(fake.voice.openMicrophone).toHaveBeenCalledTimes(1);

    unmount();
  });
});
