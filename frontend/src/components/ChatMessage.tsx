import { ACTION_LABELS } from "../lib/format";
import type { ChatEntry } from "../types";
import { AudioReply } from "./AudioReply";
import { EventCard } from "./EventCard";

interface ChatMessageProps {
  entry: ChatEntry;
  timezone: string;
  autoPlayAudio?: boolean;
  /** Speech for this reply is being generated right now. */
  synthesizing?: boolean;
  onComplete: (eventId: number) => Promise<void> | void;
  /** Called with the entry id when the reply audio finishes. */
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
      <div className="flex justify-start">
        <div className="max-w-[92%] break-words rounded-2xl rounded-bl-md border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {entry.text}
        </div>
      </div>
    );
  }

  const { reply } = entry;
  const action = reply.intent ? ACTION_LABELS[reply.intent] : undefined;
  const showCards = reply.events.length > 0 && reply.intent !== "delete_event";
  // Speech can arrive after the text (separate /api/speech request) or inline
  // with an older reply payload; both are rendered the same way.
  const audio =
    entry.audio ?? (reply.audio ? { data: reply.audio, mime: reply.audio_mime } : null);

  return (
    <div className="flex flex-col gap-2">
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
        <p className="px-1 text-[11px] uppercase tracking-[0.12em] text-ink-dim">{action}</p>
      ) : null}
      {showCards ? (
        <ul className="grid gap-2 sm:grid-cols-2">
          {reply.events.map((event) => (
            <li key={event.id}>
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
