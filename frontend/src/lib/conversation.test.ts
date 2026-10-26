import { describe, expect, it, vi } from "vitest";

import {
  ConversationLoop,
  type ConversationPhase,
  type ConversationSend,
  type VoiceTurnOutcome,
} from "./conversation";
import { isFarewellUtterance } from "./farewell";

interface HarnessOptions {
  outcomes?: VoiceTurnOutcome[];
  open?: boolean;
  begin?: boolean;
  send?: ConversationSend;
  hasSpeech?: () => boolean;
}

function makeHarness(options: HarnessOptions = {}) {
  const calls: string[] = [];
  const outcomes: VoiceTurnOutcome[] = [
    ...(options.outcomes ?? [{ kind: "text", text: "поставь задачу" }]),
  ];

  const voice = {
    open: vi.fn(async () => {
      calls.push("open");
      return options.open ?? true;
    }),
    beginTurn: vi.fn(async () => {
      calls.push("begin");
      return options.begin ?? true;
    }),
    commitTurn: vi.fn(async (): Promise<VoiceTurnOutcome> => {
      calls.push("commit");
      return outcomes.shift() ?? { kind: "empty" };
    }),
    release: vi.fn(() => {
      calls.push("release");
    }),
  };

  const defaultSend: ConversationSend = async (text, sendOptions) => {
    calls.push(`send:${text}:${String(sendOptions.closing)}`);
    return { ok: true, hasAudio: true };
  };
  const sendUtterance = vi.fn(options.send ?? defaultSend);

  const phases: ConversationPhase[] = [];
  const onPhase = vi.fn((phase: ConversationPhase) => {
    phases.push(phase);
  });
  const onActiveChange = vi.fn();
  const onError = vi.fn();
  const onFarewell = vi.fn();
  const delay = vi.fn(async (milliseconds: number) => {
    calls.push(`guard:${milliseconds}`);
  });

  const loop = new ConversationLoop({
    voice,
    sendUtterance,
    isFarewell: isFarewellUtterance,
    hasSpeech: options.hasSpeech ?? (() => true),
    onPhase,
    onActiveChange,
    onError,
    onFarewell,
    delay,
  });

  return {
    loop,
    voice,
    sendUtterance,
    phases,
    onPhase,
    onActiveChange,
    onError,
    onFarewell,
    delay,
    calls,
  };
}

describe("ConversationLoop", () => {
  it("sequences commit, send, playback and the next listening turn", async () => {
    const harness = makeHarness();
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));
    expect(harness.loop.isActive).toBe(true);
    expect(harness.loop.currentPhase).toBe("listening");

    const committing = harness.loop.commit();
    await vi.waitFor(() => expect(harness.sendUtterance).toHaveBeenCalledTimes(1));
    expect(harness.sendUtterance).toHaveBeenCalledWith("поставь задачу", { closing: false });
    await vi.waitFor(() => expect(harness.loop.currentPhase).toBe("speaking"));
    expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1);
    expect(harness.voice.release).not.toHaveBeenCalled();

    harness.loop.notifyPlaybackFinished();
    await committing;

    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(2));
    expect(harness.calls).toEqual([
      "open",
      "begin",
      "commit",
      "send:поставь задачу:false",
      "guard:400",
      "begin",
    ]);
    expect(harness.loop.currentPhase).toBe("listening");
    expect(harness.loop.isActive).toBe(true);
    expect(harness.onError).not.toHaveBeenCalled();
  });

  it("sends a short farewell with closing and ends after the reply", async () => {
    const harness = makeHarness({ outcomes: [{ kind: "text", text: "Спасибо!" }] });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));
    expect(harness.onActiveChange).toHaveBeenLastCalledWith(true);

    const committing = harness.loop.commit();
    await vi.waitFor(() => expect(harness.sendUtterance).toHaveBeenCalledTimes(1));
    expect(harness.sendUtterance).toHaveBeenCalledWith("Спасибо!", { closing: true });

    harness.loop.notifyPlaybackFinished();
    await committing;
    await vi.waitFor(() => expect(harness.onFarewell).toHaveBeenCalledTimes(1));

    expect(harness.loop.isActive).toBe(false);
    expect(harness.loop.currentPhase).toBe("ended");
    expect(harness.onActiveChange).toHaveBeenLastCalledWith(false);
    expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1);
    expect(harness.voice.release).toHaveBeenCalled();
  });

  it("keeps listening after an empty turn without sending or reporting an error", async () => {
    const harness = makeHarness({ outcomes: [{ kind: "empty" }] });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));

    await harness.loop.commit();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(2));

    expect(harness.sendUtterance).not.toHaveBeenCalled();
    expect(harness.onError).not.toHaveBeenCalled();
    expect(harness.voice.release).not.toHaveBeenCalled();
    expect(harness.loop.isActive).toBe(true);
    expect(harness.loop.currentPhase).toBe("listening");
  });

  it("does not report an error for a silent manual stop", async () => {
    const harness = makeHarness({
      outcomes: [{ kind: "error", message: "Ничего не распознано." }],
      hasSpeech: () => false,
    });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));

    await harness.loop.stop();

    expect(harness.onError).not.toHaveBeenCalled();
    expect(harness.sendUtterance).not.toHaveBeenCalled();
    expect(harness.loop.isActive).toBe(false);
    expect(harness.loop.currentPhase).toBe("idle");
    expect(harness.voice.release).toHaveBeenCalled();
    expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1);
  });

  it("commits the streaming turn on manual stop and leaves the mode", async () => {
    const harness = makeHarness({
      send: async () => ({ ok: true, hasAudio: false }),
    });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));

    await harness.loop.stop();

    expect(harness.sendUtterance).toHaveBeenCalledWith("поставь задачу", { closing: false });
    expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1);
    expect(harness.loop.isActive).toBe(false);
    expect(harness.loop.currentPhase).toBe("idle");
    expect(harness.voice.release).toHaveBeenCalled();
    expect(harness.onActiveChange).toHaveBeenLastCalledWith(false);
  });

  it("leaves the mode when the microphone is denied", async () => {
    const harness = makeHarness({ open: false });
    await harness.loop.start();

    expect(harness.voice.beginTurn).not.toHaveBeenCalled();
    expect(harness.loop.isActive).toBe(false);
    expect(harness.loop.currentPhase).toBe("idle");
    expect(harness.onActiveChange).toHaveBeenLastCalledWith(false);
    expect(harness.voice.release).toHaveBeenCalled();
  });

  it("reports a recognition error and leaves the mode", async () => {
    const harness = makeHarness({
      outcomes: [{ kind: "error", message: "Не удалось распознать речь." }],
    });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));

    await harness.loop.commit();
    await vi.waitFor(() => expect(harness.onError).toHaveBeenCalledTimes(1));

    expect(harness.onError).toHaveBeenCalledWith("Не удалось распознать речь.");
    expect(harness.sendUtterance).not.toHaveBeenCalled();
    expect(harness.loop.isActive).toBe(false);
    expect(harness.loop.currentPhase).toBe("idle");
    expect(harness.voice.release).toHaveBeenCalled();
  });

  it("waits for the guard delay before listening again when the reply has no audio", async () => {
    const harness = makeHarness({ send: async () => ({ ok: true, hasAudio: false }) });
    await harness.loop.start();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1));

    await harness.loop.commit();
    await vi.waitFor(() => expect(harness.voice.beginTurn).toHaveBeenCalledTimes(2));

    expect(harness.delay).toHaveBeenCalledWith(400);
    expect(harness.sendUtterance).toHaveBeenCalledTimes(1);
  });

  it("does not start twice when start is tapped twice", async () => {
    const harness = makeHarness();
    await Promise.all([harness.loop.start(), harness.loop.start()]);
    expect(harness.voice.open).toHaveBeenCalledTimes(1);
    expect(harness.voice.beginTurn).toHaveBeenCalledTimes(1);
  });

  it("releases the microphone when stopped during the opening handshake", async () => {
    let resolveBegin: (started: boolean) => void = () => {};
    const begin = new Promise<boolean>((resolve) => {
      resolveBegin = resolve;
    });
    const voice = {
      open: vi.fn(async () => true),
      beginTurn: vi.fn(() => begin),
      commitTurn: vi.fn(
        async (): Promise<VoiceTurnOutcome> => ({ kind: "empty" }),
      ),
      release: vi.fn(),
    };
    const sendUtterance = vi.fn(async () => ({ ok: true, hasAudio: false }));
    const loop = new ConversationLoop({
      voice,
      sendUtterance,
      hasSpeech: () => true,
    });

    const starting = loop.start();
    await vi.waitFor(() => expect(voice.beginTurn).toHaveBeenCalledTimes(1));
    await loop.stop();
    expect(loop.isActive).toBe(false);
    expect(loop.currentPhase).toBe("idle");
    expect(voice.release).toHaveBeenCalled();

    resolveBegin(true);
    await starting;

    expect(voice.release).toHaveBeenCalledTimes(2);
    expect(voice.commitTurn).not.toHaveBeenCalled();
    expect(sendUtterance).not.toHaveBeenCalled();
    expect(loop.isActive).toBe(false);
  });
});
