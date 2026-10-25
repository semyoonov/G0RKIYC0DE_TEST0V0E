import { useState, type FormEvent } from "react";
import { Mic } from "lucide-react";

import { Button } from "./ui/button";
import { Input } from "./ui/input";

interface ComposerProps {
  disabled: boolean;
  recording: boolean;
  busy: boolean;
  onSend: (text: string) => void;
  onToggleRecording: () => void;
}

export function Composer({ disabled, recording, busy, onSend, onToggleRecording }: ComposerProps) {
  const [value, setValue] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = value.trim();
    if (!text || disabled || recording) return;
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
          disabled={disabled}
        />
        <Button
          variant="secondary"
          className="w-full sm:w-auto"
          onClick={onToggleRecording}
          disabled={busy || disabled}
          aria-pressed={recording}
          aria-label={recording ? "Остановить запись" : "Записать голосом"}
        >
          {recording ? (
            <>
              <span className="size-2 animate-pulse rounded-full bg-danger" />
              Стоп
            </>
          ) : (
            <>
              <Mic className="size-4" />
              Голосом
            </>
          )}
        </Button>
        <Button type="submit" className="w-full sm:w-auto" disabled={disabled || recording || !value.trim()}>
          Отправить
        </Button>
      </div>
    </form>
  );
}
