import { useRef, type KeyboardEvent } from "react";
import { AudioLines, MessageSquareText } from "lucide-react";

import { cn } from "../lib/utils";

interface ReplyModeSwitchProps {
  speak: boolean;
  onChange: (speak: boolean) => void;
}

const OPTIONS = [
  { speak: false, label: "Текстом", Icon: MessageSquareText },
  { speak: true, label: "Голосом", Icon: AudioLines },
] as const;

/** Как ассистент отвечает: оба варианта видны сразу, выбранный подсвечен. */
export function ReplyModeSwitch({ speak, onChange }: ReplyModeSwitchProps) {
  const radios = useRef<Array<HTMLButtonElement | null>>([]);

  // Клавиатура как у группы радиокнопок: стрелки выбирают соседний вариант.
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (step === 0) return;
    event.preventDefault();
    const next = (index + step + OPTIONS.length) % OPTIONS.length;
    radios.current[next]?.focus();
    if (OPTIONS[next].speak !== speak) onChange(OPTIONS[next].speak);
  };

  return (
    <div className="inline-flex shrink-0 flex-col items-center gap-1">
      <div
        role="radiogroup"
        aria-label="Формат ответа"
        className="relative grid h-9 grid-cols-2 rounded-full border border-line bg-card p-0.5 text-[13px]"
      >
        <span
          aria-hidden="true"
          className={cn(
            "absolute inset-y-0.5 left-0.5 w-[calc(50%-0.125rem)] rounded-full bg-accent-soft ring-1 ring-accent/40 transition-transform duration-200 ease-out motion-reduce:transition-none",
            speak && "translate-x-full",
          )}
        />
        {OPTIONS.map(({ speak: value, label, Icon }, index) => {
          const selected = speak === value;
          return (
            <button
              key={label}
              ref={(node) => {
                radios.current[index] = node;
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              // В порядке Tab только выбранный вариант, между вариантами — стрелками.
              tabIndex={selected ? 0 : -1}
              onKeyDown={(event) => handleKeyDown(event, index)}
              onClick={() => {
                if (!selected) onChange(value);
              }}
              className={cn(
                "relative z-10 inline-flex items-center justify-center gap-1.5 rounded-full px-3.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
                selected ? "text-accent" : "text-ink-muted hover:text-ink",
              )}
            >
              <Icon className="size-[15px]" aria-hidden="true" />
              {label}
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-ink">(Выдавать ответ голосом или текстом)</p>
    </div>
  );
}
