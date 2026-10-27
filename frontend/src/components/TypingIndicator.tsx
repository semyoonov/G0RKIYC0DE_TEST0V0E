const DOT_DELAYS_MS = [0, 160, 320];

/** Пузырь ассистента, пока ответ ещё не пришёл: как «печатает…» в мессенджерах, только «Отвечаю». */
export function TypingIndicator() {
  return (
    <div className="flex justify-start animate-message-in motion-reduce:animate-none">
      <div className="inline-flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-line bg-panel px-4 py-3 text-sm leading-relaxed text-ink-muted">
        Отвечаю
        <span className="inline-flex items-end gap-1 pt-1.5" aria-hidden="true">
          {DOT_DELAYS_MS.map((delay) => (
            <span
              key={delay}
              className="size-1 rounded-full bg-ink-muted animate-typing-dot motion-reduce:animate-none"
              style={{ animationDelay: `${delay}ms` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}
