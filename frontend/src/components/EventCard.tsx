import { useState } from "react";

import { EVENT_STATUS_LABELS, EVENT_TYPE_LABELS, formatEventTime } from "../lib/format";
import type { AssistantEvent } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

interface EventCardProps {
  event: AssistantEvent;
  timezone: string;
  onComplete: (eventId: number) => Promise<void> | void;
}

export function EventCard({ event, timezone, onComplete }: EventCardProps) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const time = formatEventTime(event.starts_at ?? event.remind_at, timezone);
  const statusVariant = event.status === "done" ? "success" : event.status === "cancelled" ? "danger" : "neutral";

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

  return (
    <Card className="h-full">
      <CardHeader className="gap-2">
        <Badge variant="accent">{EVENT_TYPE_LABELS[event.type]}</Badge>
        <Badge variant={statusVariant}>{EVENT_STATUS_LABELS[event.status]}</Badge>
      </CardHeader>
      <CardContent className="pt-2">
        <CardTitle>{event.title}</CardTitle>
        {time ? <p className="mt-1 text-xs text-ink-muted">{time}</p> : null}
        {event.status === "pending" ? (
          <Button variant="outline" size="sm" className="mt-3" disabled={busy} onClick={complete}>
            выполнено
          </Button>
        ) : null}
        {failed ? (
          <p className="mt-2 text-xs text-danger" role="alert">
            Не удалось отметить выполненной.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
