import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VoiceTurnOutcome } from "../lib/conversation";
import type { VoiceController } from "./useVoiceStream";
import {
  useVoiceConversation,
  type VoiceConversationController,
} from "./useVoiceConversation";

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
    mute: vi.fn(),
    unmute: vi.fn(),
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

function baseProps(fake: FakeVoice, sendUtterance: ReturnType<typeof vi.fn>) {
  return {
    voice: fake.voice,
    sendUtterance,
    reportError: vi.fn(),
    pausePlayback: vi.fn(),
    telemetry: vi.fn(),
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
    const props = baseProps(fake, sendUtterance);
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
    const props = baseProps(fake, sendUtterance);
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
    const props = baseProps(fake, sendUtterance);
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
});

describe("useVoiceConversation muted turn and barge-in", () => {
  interface SpeakingTurn {
    fake: FakeVoice;
    props: ReturnType<typeof baseProps>;
    result: { current: VoiceConversationController };
    unmount: () => void;
  }

  async function startSpeakingTurn(options: { hasAudio: boolean }): Promise<SpeakingTurn> {
    const fake = makeFakeVoice();
    const sendUtterance = vi.fn(async () => ({ ok: true, hasAudio: options.hasAudio }));
    const props = baseProps(fake, sendUtterance);
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
    rerender({ ...props, voice: { ...fake.voice, partial: "поставь задачу" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500);
    });
    await act(async () => {});
    return { fake, props, result, unmount };
  }

  it("keeps the next turn muted and unmutes it when playback ends", async () => {
    vi.useFakeTimers();
    const { fake, props, result, unmount } = await startSpeakingTurn({ hasAudio: true });

    expect(fake.voice.beginTurn).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fake.voice.beginTurn).mock.calls[1][0]).toEqual({ muted: true });
    expect(result.current.phase).toBe("speaking");
    expect(fake.voice.unmute).not.toHaveBeenCalled();
    expect(props.pausePlayback).not.toHaveBeenCalled();

    await act(async () => {
      result.current.notifyPlaybackFinished();
    });

    expect(fake.voice.unmute).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("listening");
    // Neither the microphone nor the websocket is reopened.
    expect(fake.voice.beginTurn).toHaveBeenCalledTimes(2);
    expect(props.pausePlayback).not.toHaveBeenCalled();
    expect(props.telemetry).toHaveBeenCalledWith("phase", "listening", "");

    unmount();
  });

  it("barge-in pauses the reply audio, unmutes and keeps the same turn", async () => {
    vi.useFakeTimers();
    const { fake, props, result, unmount } = await startSpeakingTurn({ hasAudio: true });

    expect(result.current.phase).toBe("speaking");

    act(() => {
      fake.emit(0.12);
      vi.advanceTimersByTime(120);
      fake.emit(0.12);
      vi.advanceTimersByTime(140);
      fake.emit(0.12);
    });
    await act(async () => {});

    expect(props.pausePlayback).toHaveBeenCalledTimes(1);
    expect(fake.voice.unmute).toHaveBeenCalled();
    expect(result.current.phase).toBe("listening");
    expect(fake.voice.beginTurn).toHaveBeenCalledTimes(2);
    expect(props.telemetry).toHaveBeenCalledWith(
      "barge_in",
      "speaking",
      expect.any(String),
    );

    unmount();
  });

  it("does not barge in on quiet input below the threshold", async () => {
    vi.useFakeTimers();
    const { fake, props, result, unmount } = await startSpeakingTurn({ hasAudio: true });

    act(() => {
      for (let index = 0; index < 20; index += 1) {
        fake.emit(0.02);
        vi.advanceTimersByTime(40);
      }
    });
    await act(async () => {});

    expect(props.pausePlayback).not.toHaveBeenCalled();
    expect(fake.voice.unmute).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("speaking");

    unmount();
  });

  it("does not barge in on a single short noise", async () => {
    vi.useFakeTimers();
    const { fake, props, result, unmount } = await startSpeakingTurn({ hasAudio: true });

    act(() => {
      fake.emit(0.4);
      for (let index = 0; index < 25; index += 1) {
        vi.advanceTimersByTime(40);
        fake.emit(0.001);
      }
    });
    await act(async () => {});

    expect(props.pausePlayback).not.toHaveBeenCalled();
    expect(result.current.phase).toBe("speaking");

    unmount();
  });

  it("unmutes as soon as a reply without speech arrives", async () => {
    vi.useFakeTimers();
    const { fake, props, result, unmount } = await startSpeakingTurn({ hasAudio: false });

    expect(fake.voice.beginTurn).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fake.voice.beginTurn).mock.calls[1][0]).toEqual({ muted: true });
    expect(fake.voice.unmute).toHaveBeenCalledTimes(1);
    expect(result.current.phase).toBe("listening");
    expect(props.pausePlayback).not.toHaveBeenCalled();
    const phases = props.telemetry.mock.calls
      .filter((call) => call[0] === "phase")
      .map((call) => call[1]);
    expect(phases).not.toContain("speaking");

    unmount();
  });
});

describe("useVoiceConversation failures", () => {
  it("leaves the mode when the voice layer reports an error", async () => {
    const fake = makeFakeVoice();
    const props = baseProps(fake, vi.fn(async () => ({ ok: true, hasAudio: false })));
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
    expect(props.telemetry).toHaveBeenCalledWith(
      "stream_failed",
      expect.any(String),
      "Не удалось включить микрофон.",
    );

    unmount();
  });

  it("fires a best-effort warmup whenever the mode is entered", async () => {
    const fake = makeFakeVoice();
    const warmup = vi.fn();
    const props = { ...baseProps(fake, vi.fn(async () => ({ ok: true, hasAudio: false }))), warmup };
    const { result, unmount } = renderHook(() => useVoiceConversation(props));

    await act(async () => {
      await result.current.start();
    });

    expect(warmup).toHaveBeenCalledTimes(1);
    expect(result.current.active).toBe(true);
    expect(fake.voice.openMicrophone).toHaveBeenCalledTimes(1);

    unmount();
  });
});
