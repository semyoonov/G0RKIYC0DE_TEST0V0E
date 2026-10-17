interface LiveTranscriptProps {
  text: string;
}

export function LiveTranscript({ text }: LiveTranscriptProps) {
  if (!text) return null;
  return (
    <p className="px-4 pt-2 text-sm text-ink-muted sm:px-6" aria-live="polite">
      Слушаю: {text}
    </p>
  );
}
