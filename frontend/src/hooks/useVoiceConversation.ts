import { useCallback, useEffect, useRef, useState } from "react";

import { reportTelemetry } from "../lib/api";
import { BargeInDetector } from "../lib/bargein";
import {
  ConversationLoop,
  type ConversationPhase,
  type ConversationSend,
} from "../lib/conversation";
import { AutoCommitDetector, VAD_ENERGY_THRESHOLD, VAD_SILENCE_MS } from "../lib/vad";
import type { VoiceController } from "./useVoiceStream";

export const FAREWELL_HINT =
  "Диалог завершён. Нажмите «Голосом», чтобы начать снова.";

const PHASE_STATUS: Record<ConversationPhase, string> = {
  idle: "",
  listening: "Слушаю… Закончите фразу, и я отправлю её после паузы.",
  thinking: "Распознаю…",
  speaking: "Отвечаю…",
  ended: "",
};

export type TelemetrySink = (
  event: string,
  phase: ConversationPhase,
  detail?: string,
) => void;

export interface VoiceConversationOptions {
  voice: VoiceController;
  sendUtterance: ConversationSend;
  reportError: (message: string) => void;
  /** Best-effort model warmup; called every time the mode is entered. */
  warmup?: () => void;
  /** Interrupts the reply audio when the user starts talking over it. */
  pausePlayback?: () => void;
  /** Diagnostics sink; defaults to the real /api/telemetry reporter. */
  telemetry?: TelemetrySink;
}

export interface VoiceConversationController {
  active: boolean;
  phase: ConversationPhase;
  status: string;
  hint: string | null;
  supported: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  toggle: () => Promise<void>;
  notifyPlaybackFinished: () => void;
}

function pauseAllPlayback(): void {
  if (typeof document === "undefined") return;
  document.querySelectorAll("audio").forEach((node) => {
    try {
      node.pause();
    } catch {
      // The element was already stopped.
    }
  });
}

/**
 * Drives a hands-free conversation: the microphone is opened once, VAD decides
 * when a turn is committed, and the next streaming turn is opened muted while
 * the answer is generated. It is unmuted after playback — or immediately when
 * the user talks over the reply (barge-in).
 */
export function useVoiceConversation(
  options: VoiceConversationOptions,
): VoiceConversationController {
  const [active, setActive] = useState(false);
  const [phase, setPhase] = useState<ConversationPhase>("idle");
  const [hint, setHint] = useState<string | null>(null);

  const activeRef = useRef(false);
  const phaseRef = useRef<ConversationPhase>("idle");
  const timerRef = useRef<number | null>(null);
  const detectorRef = useRef<AutoCommitDetector | null>(null);
  if (detectorRef.current === null) {
    detectorRef.current = new AutoCommitDetector({
      threshold: VAD_ENERGY_THRESHOLD,
      silenceMs: VAD_SILENCE_MS,
    });
  }
  const bargeInRef = useRef<BargeInDetector | null>(null);
  if (bargeInRef.current === null) {
    bargeInRef.current = new BargeInDetector();
  }

  const voiceRef = useRef(options.voice);
  voiceRef.current = options.voice;
  const sendRef = useRef(options.sendUtterance);
  sendRef.current = options.sendUtterance;
  const reportErrorRef = useRef(options.reportError);
  reportErrorRef.current = options.reportError;
  const warmupRef = useRef(options.warmup);
  warmupRef.current = options.warmup;
  const pausePlaybackRef = useRef(options.pausePlayback ?? pauseAllPlayback);
  pausePlaybackRef.current = options.pausePlayback ?? pauseAllPlayback;
  const telemetryRef = useRef<TelemetrySink>(options.telemetry ?? reportTelemetry);
  telemetryRef.current = options.telemetry ?? reportTelemetry;
  const loopRef = useRef<ConversationLoop | null>(null);
  const reportedVoiceErrorRef = useRef<string | null>(null);

  const clearCommitTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const resetVad = useCallback(() => {
    detectorRef.current?.reset();
    clearCommitTimer();
  }, [clearCommitTimer]);

  const armCommitTimer = useCallback(() => {
    const detector = detectorRef.current;
    clearCommitTimer();
    if (!detector || !activeRef.current || phaseRef.current !== "listening") return;
    const deadline = detector.commitDeadline();
    if (deadline === null) return;

    const schedule = (wait: number) => {
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        if (!activeRef.current || phaseRef.current !== "listening") return;
        const current = detectorRef.current;
        if (!current) return;
        const next = current.commitDeadline();
        if (next === null) return;
        const now = Date.now();
        if (now < next) {
          schedule(next - now);
          return;
        }
        void loopRef.current?.commit();
      }, Math.max(0, wait));
    };
    schedule(deadline - Date.now());
  }, [clearCommitTimer]);

  if (loopRef.current === null) {
    loopRef.current = new ConversationLoop({
      voice: {
        open: () => voiceRef.current.openMicrophone(),
        beginTurn: (turnOptions) => voiceRef.current.beginTurn(turnOptions),
        commitTurn: () => voiceRef.current.commitTurn(),
        release: () => voiceRef.current.releaseMicrophone(),
        unmute: () => voiceRef.current.unmute(),
      },
      sendUtterance: (text, sendOptions) => sendRef.current(text, sendOptions),
      hasSpeech: () => detectorRef.current?.spoke ?? false,
      onPhase: (next) => {
        phaseRef.current = next;
        setPhase(next);
        resetVad();
      },
      onActiveChange: (next) => {
        activeRef.current = next;
        setActive(next);
      },
      onError: (message) => reportErrorRef.current(message),
      onFarewell: () => setHint(FAREWELL_HINT),
      onTelemetry: (event, currentPhase, detail) =>
        telemetryRef.current(event, currentPhase, detail),
    });
  }

  const subscribeEnergy = options.voice.subscribeEnergy;

  useEffect(() => {
    if (!active || phase !== "listening") return;
    const detector = detectorRef.current;
    detector?.reset();
    const unsubscribe = subscribeEnergy((energy) => {
      if (!activeRef.current || phaseRef.current !== "listening") return;
      if (detector?.noteEnergy(energy, Date.now())) armCommitTimer();
    });
    return () => {
      unsubscribe();
      clearCommitTimer();
    };
  }, [active, phase, subscribeEnergy, armCommitTimer, clearCommitTimer]);

  useEffect(() => {
    if (!active || phase !== "speaking") return;
    const detector = bargeInRef.current;
    if (!detector) return;
    detector.reset();
    const unsubscribe = subscribeEnergy((energy) => {
      if (!activeRef.current || phaseRef.current !== "speaking") return;
      // Sustained input above the barge-in threshold means the user is talking
      // over the answer: stop the audio and keep listening in the same turn.
      if (!detector.noteEnergy(energy, Date.now())) return;
      pausePlaybackRef.current();
      voiceRef.current.unmute();
      telemetryRef.current("barge_in", "speaking", "speech over reply audio");
      loopRef.current?.notifyPlaybackFinished();
    });
    return unsubscribe;
  }, [active, phase, subscribeEnergy]);

  const partial = options.voice.partial;
  const lastPartialRef = useRef("");

  useEffect(() => {
    if (!active || phase !== "listening") {
      lastPartialRef.current = "";
      return;
    }
    const detector = detectorRef.current;
    if (partial) {
      lastPartialRef.current = partial;
      detector?.setPartial(partial);
      armCommitTimer();
      return;
    }
    if (!lastPartialRef.current) return;
    // The recognizer finalised the phrase itself: an empty partial that follows a
    // non-empty one is its own endpoint signal, so the turn commits without the
    // silence window.
    lastPartialRef.current = "";
    detector?.setPartial("");
    if (detector?.spoke) {
      void loopRef.current?.commit();
    }
  }, [partial, active, phase, armCommitTimer]);

  const start = useCallback(async () => {
    if (!voiceRef.current.streaming) return;
    setHint(null);
    voiceRef.current.clearError();
    if (typeof document !== "undefined") {
      // Entering hands-free mode must not capture an older reply still playing.
      document.querySelectorAll("audio").forEach((node) => node.pause());
    }
    const warmup = warmupRef.current;
    if (warmup) {
      try {
        void Promise.resolve(warmup()).catch(() => {});
      } catch {
        // Warmup must never block the conversation.
      }
    }
    await loopRef.current?.start();
  }, []);

  const stop = useCallback(async () => {
    await loopRef.current?.stop();
  }, []);

  const toggle = useCallback(async () => {
    const loop = loopRef.current;
    if (!loop) return;
    if (loop.isActive) await stop();
    else await start();
  }, [start, stop]);

  const notifyPlaybackFinished = useCallback(() => {
    loopRef.current?.notifyPlaybackFinished();
  }, []);

  // A denied microphone or a broken voice stream must never leave the UI
  // stuck in conversation mode; the same effect reports the failure once.
  useEffect(() => {
    const message = options.voice.error;
    if (!message) {
      reportedVoiceErrorRef.current = null;
      return;
    }
    if (message !== reportedVoiceErrorRef.current) {
      reportedVoiceErrorRef.current = message;
      telemetryRef.current("stream_failed", phaseRef.current, message);
    }
    if (active) void stop();
  }, [active, options.voice.error, stop]);

  useEffect(() => {
    return () => {
      clearCommitTimer();
      loopRef.current?.dispose();
    };
  }, [clearCommitTimer]);

  return {
    active,
    phase,
    status: active ? PHASE_STATUS[phase] : "",
    hint,
    supported: options.voice.streaming,
    start,
    stop,
    toggle,
    notifyPlaybackFinished,
  };
}
