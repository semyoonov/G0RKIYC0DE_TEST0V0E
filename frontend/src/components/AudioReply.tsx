import { useEffect, useMemo, useRef } from "react";

import { decodeAudio } from "../lib/audio";
import { Button } from "./ui/button";

interface AudioReplyProps {
  data: string;
  mime: string | null;
}

export function AudioReply({ data, mime }: AudioReplyProps) {
  const url = useMemo(() => decodeAudio(data, mime), [data, mime]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);

  useEffect(() => {
    void audioRef.current?.play().catch(() => {});
  }, [url]);

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
