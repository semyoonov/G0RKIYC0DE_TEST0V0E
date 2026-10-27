import { useState } from "react";
import { Bell, Calendar, Check, CheckSquare, Clock } from "lucide-react";

import { EVENT_STATUS_LABELS, EVENT_TYPE_LABELS, formatEventTime } from "../lib/format";
import type { AssistantEvent, EventType } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

interface EventCardProps {
  event: AssistantEvent;
  timezone: string;
  onComplete: (eventId: number) => Promise<void> | void;
}

const TYPE_ICONS: Record<EventType, typeof Calendar> = {
  meeting: Calendar,
  reminder: Bell,
  task: CheckSquare,
};

const TYPE_VARIANTS: Record<EventType, "accent" | "warning" | "neutral"> = {
  meeting: "accent",
  reminder: "warning",
  task: "neutral",
};

export function EventCard({ event, timezone, onComplete }: EventCardProps) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const time = formatEventTime(event.starts_at ?? event.remind_at, timezone);
  const isDone = event.status === "done";
  const isCancelled = event.status === "cancelled";
  const isPending = event.status === "pending";

  const statusVariant = isDone ? "success" : isCancelled ? "danger" : "neutral";
  const typeVariant = TYPE_VARIANTS[event.type] ?? "neutral";
  const TypeIcon = TYPE_ICONS[event.type] ?? Calendar;

  const complete = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await onComplete(event.id);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const borderAccent = isDone
    ? "border-l-[3px] border-l-emerald-500/60 bg-card/60 opacity-80"
    : isCancelled
      ? "border-l-[3px] border-l-danger/60 opacity-60"
      : event.type === "reminder"
        ? "border-l-[3px] border-l-amber-400 shadow-[0_2px_12px_rgba(0,0,0,0.24)] hover:border-l-amber-300"
        : event.type === "meeting"
          ? "border-l-[3px] border-l-sky-400 shadow-[0_2px_12px_rgba(0,0,0,0.24)] hover:border-l-sky-300"
          : "border-l-[3px] border-l-accent shadow-[0_2px_12px_rgba(0,0,0,0.24)] hover:border-l-accent-hover";

  return (
    <article
      className={`group relative flex h-full flex-col justify-between rounded-xl border border-line/80 bg-card p-3.5 transition-[border-color,box-shadow] duration-200 hover:border-line-hover ${borderAccent}`}
    >
      <div>
        <header className="flex items-center justify-between gap-2">
          <Badge variant={typeVariant} className="gap-1.5 rounded-md px-2 py-0.5 font-sans lowercase">
            <TypeIcon className="size-3 shrink-0" aria-hidden="true" />
            <span>{EVENT_TYPE_LABELS[event.type]}</span>
          </Badge>
          <Badge variant={statusVariant} className="rounded-md px-2 py-0.5 font-sans lowercase">
            {isDone ? <Check className="mr-1 size-3 shrink-0" aria-hidden="true" /> : null}
            <span>{EVENT_STATUS_LABELS[event.status]}</span>
          </Badge>
        </header>

        <div className="my-2.5">
          <h3
            className={`break-words text-[15px] font-semibold leading-snug transition-colors ${
              isDone ? "text-ink-muted line-through decoration-line/80" : "text-ink"
            }`}
          >
            {event.title}
          </h3>

          {event.description ? (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-ink-dim">
              {event.description}
            </p>
          ) : null}
        </div>
      </div>

      <div>
        <footer className="mt-1 flex flex-wrap items-center justify-between gap-2 border-t border-line/40 pt-2.5">
          {time ? (
            <div className="inline-flex items-center gap-1.5 rounded-md border border-line/40 bg-raised/50 px-2 py-1 font-mono text-xs text-ink-muted">
              <Clock className="size-3.5 shrink-0 text-ink-dim" aria-hidden="true" />
              <span>{time}</span>
            </div>
          ) : (
            <div />
          )}

          {isPending ? (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={complete}
              className="h-7 gap-1.5 rounded-md border-line/80 bg-raised/70 px-2.5 text-xs font-medium text-ink transition-colors hover:border-accent/60 hover:bg-raised hover:text-accent active:translate-y-px"
            >
              <Check className="size-3.5 text-accent" aria-hidden="true" />
              <span>выполнено</span>
            </Button>
          ) : null}
        </footer>

        {failed ? (
          <p className="mt-1.5 text-xs text-danger" role="alert">
            Не удалось отметить выполненной.
          </p>
        ) : null}
      </div>
    </article>
  );
}
