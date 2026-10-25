import { ACTION_LABELS } from "../lib/format";
import type { ChatEntry } from "../types";
import { AudioReply } from "./AudioReply";
import { EventCard } from "./EventCard";

interface ChatMessageProps {
  entry: ChatEntry;
  timezone: string;
  autoPlayAudio?: boolean;
  onComplete: (eventId: number) => Promise<void> | void;
}

export function ChatMessage({ entry, timezone, autoPlayAudio = true, onComplete }: ChatMessageProps) {
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

  return (
    <div className="flex flex-col gap-2">
      <div className="max-w-[92%] break-words rounded-2xl rounded-bl-md border border-line bg-panel px-4 py-3 text-sm leading-relaxed text-ink">
        {reply.reply}
      </div>
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
      {reply.audio ? <AudioReply data={reply.audio} mime={reply.audio_mime} autoPlay={autoPlayAudio} /> : null}
    </div>
  );
}
