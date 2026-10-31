import { ACTION_LABELS } from "../lib/format";
import type { ChatEntry } from "../types";
import { AudioReply } from "./AudioReply";
import { EventCard } from "./EventCard";

interface ChatMessageProps {
  entry: ChatEntry;
  timezone: string;
  autoPlayAudio?: boolean;
  /** Речь для этого ответа генерируется прямо сейчас. */
  synthesizing?: boolean;
  onComplete: (eventId: number) => Promise<void> | void;
  /** Вызывается с id реплики, когда звук ответа заканчивается. */
  onReplyAudioEnd?: (entryId: string) => void;
}

export function ChatMessage({
  entry,
  timezone,
  autoPlayAudio = true,
  synthesizing = false,
  onComplete,
  onReplyAudioEnd,
}: ChatMessageProps) {
  if (entry.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[92%] break-words rounded-2xl rounded-br-md bg-accent px-4 py-3 text-sm leading-relaxed text-white">
          {entry.text}
        </div>
      </div>
    );
  }

  if (entry.role === "error") {
    return (
      <div className="flex justify-start animate-message-in motion-reduce:animate-none">
        <div className="max-w-[92%] break-words rounded-2xl rounded-bl-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {entry.text}
        </div>
      </div>
    );
  }

  const { reply } = entry;
  // Неудачный или уточняющий ход сохраняет intent, но событий не несёт; подписываем только реальные исходы.
  const changed = reply.events.length > 0 || reply.intent === "delete_event";
  const action = reply.intent && changed ? ACTION_LABELS[reply.intent] : undefined;
  const showCards = reply.events.length > 0 && reply.intent !== "delete_event";
  // Речь приходит либо после текста (отдельный запрос /api/speech), либо внутри
  // старого ответа; отрисовка в обоих случаях одна и та же.
  const audio =
    entry.audio ?? (reply.audio ? { data: reply.audio, mime: reply.audio_mime } : null);

  return (
    // Ответ мягко проявляется на месте пузыря «Отвечаю».
    <div className="flex flex-col gap-2 animate-message-in motion-reduce:animate-none">
      <div className="max-w-[92%] break-words rounded-2xl rounded-bl-md border border-line bg-panel px-4 py-3 text-sm leading-relaxed text-ink">
        {reply.reply}
      </div>
      {synthesizing ? (
        <p className="flex items-center gap-2 px-1 text-[11px] text-ink-muted" data-testid="speech-pending">
          <span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
          Озвучиваю ответ…
        </p>
      ) : null}
      {action ? (
        <p className="px-1 text-xs font-medium text-ink-muted">{action}</p>
      ) : null}
      {showCards ? (
        <ul className="grid gap-2.5 sm:grid-cols-2">
          {reply.events.map((event) => (
            <li key={event.id} className="min-w-0">
              <EventCard event={event} timezone={timezone} onComplete={onComplete} />
            </li>
          ))}
        </ul>
      ) : null}
      {audio ? (
        <AudioReply
          data={audio.data}
          mime={audio.mime}
          autoPlay={autoPlayAudio}
          onComplete={() => onReplyAudioEnd?.(entry.id)}
        />
      ) : null}
    </div>
  );
}
