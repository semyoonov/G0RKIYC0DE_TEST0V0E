import { useState, type FormEvent } from "react";
import { Mic } from "lucide-react";

import type { ConversationPhase } from "../lib/conversation";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

interface ComposerProps {
  disabled: boolean;
  recording: boolean;
  busy: boolean;
  conversationActive?: boolean;
  conversationPhase?: ConversationPhase;
  onSend: (text: string) => void;
  onToggleRecording: () => void;
}

export function Composer({
  disabled,
  recording,
  busy,
  conversationActive = false,
  conversationPhase = "idle",
  onSend,
  onToggleRecording,
}: ComposerProps) {
  const [value, setValue] = useState("");
  const active = conversationActive || recording;

  const phaseTitle =
    conversationPhase === "thinking"
      ? "Распознаю"
      : conversationPhase === "speaking"
        ? "Отвечаю"
        : "Слушаю";
  const label = conversationActive ? "Слушаю…" : recording ? "Стоп" : "Голосом";
  const ariaLabel = conversationActive
    ? `${phaseTitle}. Остановить разговор и выключить микрофон`
    : recording
      ? "Остановить запись"
      : "Записать голосом";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = value.trim();
    if (!text || disabled || active) return;
    setValue("");
    onSend(text);
  };

  return (
    <form onSubmit={submit} className="border-t border-line/70 bg-panel/40 px-4 py-3 sm:px-6">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center">
        <Input
          className="col-span-2 sm:col-span-1"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Что запланировать?"
          aria-label="Сообщение"
          autoComplete="off"
          enterKeyHint="send"
          maxLength={4000}
          disabled={disabled || conversationActive}
        />
        <Button
          variant="secondary"
          className="w-full sm:w-auto"
          onClick={onToggleRecording}
          disabled={busy || disabled}
          aria-pressed={active}
          aria-label={ariaLabel}
        >
          {active ? (
            <>
              <span className="size-2 animate-pulse rounded-full bg-danger" />
              {label}
            </>
          ) : (
            <>
              <Mic className="size-4" />
              {label}
            </>
          )}
        </Button>
        {conversationActive ? (
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            onClick={onToggleRecording}
            aria-label="Остановить разговор и выключить микрофон"
          >
            Стоп
          </Button>
        ) : (
          <Button
            type="submit"
            className="w-full sm:w-auto"
            disabled={disabled || active || !value.trim()}
          >
            Отправить
          </Button>
        )}
      </div>
    </form>
  );
}
