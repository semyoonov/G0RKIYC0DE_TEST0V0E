import { useCallback, useEffect, useRef, useState } from "react";

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

export interface VoiceConversationOptions {
  voice: VoiceController;
  sendUtterance: ConversationSend;
  reportError: (message: string) => void;
  /** Best-effort model warmup; called every time the mode is entered. */
  warmup?: () => void;
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

/**
 * Drives a hands-free conversation: the microphone is opened once, VAD decides
 * when a turn is committed, and the next listening turn starts only after the
 * reply audio has finished.
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

  const voiceRef = useRef(options.voice);
  voiceRef.current = options.voice;
  const sendRef = useRef(options.sendUtterance);
  sendRef.current = options.sendUtterance;
  const reportErrorRef = useRef(options.reportError);
  reportErrorRef.current = options.reportError;
  const warmupRef = useRef(options.warmup);
  warmupRef.current = options.warmup;
  const loopRef = useRef<ConversationLoop | null>(null);

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
        beginTurn: () => voiceRef.current.beginTurn(),
        commitTurn: () => voiceRef.current.commitTurn(),
        release: () => voiceRef.current.releaseMicrophone(),
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

  const partial = options.voice.partial;

  useEffect(() => {
    if (!active || phase !== "listening") return;
    detectorRef.current?.setPartial(partial);
    armCommitTimer();
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
  // stuck in conversation mode.
  useEffect(() => {
    if (!active || !options.voice.error) return;
    void stop();
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
