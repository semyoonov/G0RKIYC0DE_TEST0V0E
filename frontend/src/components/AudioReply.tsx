import { useCallback, useEffect, useMemo, useRef } from "react";

import { decodeAudio } from "../lib/audio";
import { Button } from "./ui/button";

interface AudioReplyProps {
  data: string;
  mime: string | null;
  autoPlay?: boolean;
  /** Срабатывает один раз, когда воспроизведение закончилось, сорвалось или не началось. */
  onComplete?: () => void;
}

export function AudioReply({ data, mime, autoPlay = true, onComplete }: AudioReplyProps) {
  const url = useMemo(() => decodeAudio(data, mime), [data, mime]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const settledRef = useRef(false);
  const autoPlayAttempted = useRef(false);
  const fallbackTimer = useRef<number | null>(null);
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  const clearFallback = useCallback(() => {
    if (fallbackTimer.current !== null) {
      window.clearTimeout(fallbackTimer.current);
      fallbackTimer.current = null;
    }
  }, []);

  const settle = useCallback(() => {
    if (settledRef.current) return;
    settledRef.current = true;
    clearFallback();
    onCompleteRef.current?.();
  }, [clearFallback]);

  const requestPlayback = useCallback(
    (audio: HTMLAudioElement) => {
      try {
        const started = audio.play();
        // Старые движки и jsdom могут вернуть undefined вместо промиса.
        if (started && typeof started.catch === "function") {
          void started.catch(() => settle());
        }
      } catch {
        settle();
      }
    },
    [settle],
  );

  useEffect(() => {
    settledRef.current = false;
    autoPlayAttempted.current = false;
    return () => {
      if (url) URL.revokeObjectURL(url);
      clearFallback();
    };
  }, [url, clearFallback]);

  useEffect(() => {
    if (!url) settle();
  }, [url, settle]);

  useEffect(() => {
    if (!url || autoPlayAttempted.current) return;
    autoPlayAttempted.current = true;
    if (!autoPlay) return;
    const audio = audioRef.current;
    if (!audio) return;
    requestPlayback(audio);
  }, [url, autoPlay, requestPlayback]);

  useEffect(() => {
    // Воспроизведения не будет, поэтому ход без рук не должен его ждать.
    if (!url || autoPlay) return;
    settle();
  }, [url, autoPlay, settle]);

  const startFallbackTimer = () => {
    clearFallback();
    const duration = audioRef.current?.duration;
    if (duration === undefined || !Number.isFinite(duration) || duration <= 0) return;
    // Зависший элемент не должен навсегда замораживать диалог.
    fallbackTimer.current = window.setTimeout(settle, duration * 1000 + 2000);
  };

  if (!url) return null;

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          const audio = audioRef.current;
          if (!audio) return;
          settledRef.current = false;
          clearFallback();
          audio.currentTime = 0;
          requestPlayback(audio);
        }}
      >
        Прослушать ответ
      </Button>
      <audio
        ref={audioRef}
        src={url}
        preload="auto"
        className="hidden"
        onEnded={settle}
        onError={settle}
        onPlay={startFallbackTimer}
        // Пауза из-за перебивания не должна оставлять страховочный таймер взведённым.
        onPause={clearFallback}
      />
    </div>
  );
}
