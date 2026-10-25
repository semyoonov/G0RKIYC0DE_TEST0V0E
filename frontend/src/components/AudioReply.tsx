import { useEffect, useMemo, useRef } from "react";

import { decodeAudio } from "../lib/audio";
import { Button } from "./ui/button";

interface AudioReplyProps {
  data: string;
  mime: string | null;
  autoPlay?: boolean;
}

export function AudioReply({ data, mime, autoPlay = true }: AudioReplyProps) {
  const url = useMemo(() => decodeAudio(data, mime), [data, mime]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);

  useEffect(() => {
    if (!autoPlay) return;
    void audioRef.current?.play().catch(() => {});
  }, [url, autoPlay]);

  if (!url) return null;

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          if (!audioRef.current) return;
          audioRef.current.currentTime = 0;
          void audioRef.current.play().catch(() => {});
        }}
      >
        Прослушать ответ
      </Button>
      <audio ref={audioRef} src={url} preload="auto" className="hidden" />
    </div>
  );
}
