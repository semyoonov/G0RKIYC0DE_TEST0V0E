import { useCallback, useEffect, useRef, useState } from "react";

import { reportTelemetry } from "../lib/api";
import { BARGE_IN_STARTUP_GUARD_MS, BargeInDetector } from "../lib/bargein";
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
  warmup?: () => void;
  /** Прерывает звук ответа, когда пользователь начинает говорить поверх него. */
  pausePlayback?: () => void;
  /** Приёмник диагностики; по умолчанию настоящий репортёр /api/telemetry. */
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
    }
  });
}

/**
 * Ведёт диалог без рук: микрофон открывается один раз, VAD решает, когда ход
 * завершается, а следующий потоковый ход открывается приглушённым на время
 * генерации ответа. Заглушение снимается после воспроизведения — или сразу,
 * если пользователь заговорил поверх ответа (перебивание).
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
    const startedAt = Date.now();
    const unsubscribe = subscribeEnergy((energy) => {
      if (!activeRef.current || phaseRef.current !== "speaking") return;
      if (Date.now() - startedAt < BARGE_IN_STARTUP_GUARD_MS) return;
      // Длительный сигнал выше порога перебивания означает, что пользователь
      // говорит поверх ответа: гасим звук и слушаем дальше в том же ходе.
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
    // Распознаватель завершил фразу сам: пустая расшифровка после непустой
    // сама по себе означает конец, поэтому ход завершается без окна тишины.
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
      // Вход в режим без рук не должен подхватывать ещё играющий старый ответ.
      document.querySelectorAll("audio").forEach((node) => node.pause());
    }
    const warmup = warmupRef.current;
    if (warmup) {
      try {
        void Promise.resolve(warmup()).catch(() => {});
      } catch {
        // Прогрев не должен блокировать диалог.
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

  // Отказ в микрофоне или сломанный голосовой поток не должны оставлять
  // интерфейс в режиме диалога; сбой сообщается один раз.
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
