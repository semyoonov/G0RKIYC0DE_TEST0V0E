import type { EventStatus, EventType } from "../types";

export const EVENT_TYPE_LABELS: Record<EventType, string> = {
  task: "задача",
  meeting: "встреча",
  reminder: "напоминание",
};

export const EVENT_STATUS_LABELS: Record<EventStatus, string> = {
  pending: "не выполнено",
  done: "выполнено",
  cancelled: "отменено",
};

export const ACTION_LABELS: Record<string, string> = {
  create_task: "Создано",
  create_meeting: "Создано",
  update_event: "Изменено",
  complete_event: "Выполнено",
  delete_event: "Удалено",
};

const DAY_MS = 86_400_000;

function zonedDayNumber(value: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone,
  }).formatToParts(value);
  const fields: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") fields[part.type] = part.value;
  }
  return Date.UTC(Number(fields.year), Number(fields.month) - 1, Number(fields.day));
}

export function formatEventTime(value: string | null, timeZone: string, now: Date = new Date()): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const time = new Intl.DateTimeFormat("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(date);
  const difference = Math.round((zonedDayNumber(date, timeZone) - zonedDayNumber(now, timeZone)) / DAY_MS);

  if (difference === 0) return `сегодня в ${time}`;
  if (difference === 1) return `завтра в ${time}`;
  if (difference === -1) return `вчера в ${time}`;

  const day = new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "long",
    timeZone,
  }).format(date);
  return `${day} в ${time}`;
}
