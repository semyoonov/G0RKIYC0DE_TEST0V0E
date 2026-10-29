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

const RRULE_RU_MAP: Record<string, string> = {
  "FREQ=WEEKLY;BYDAY=MO": "каждый понедельник",
  "FREQ=WEEKLY;BYDAY=TU": "каждый вторник",
  "FREQ=WEEKLY;BYDAY=WE": "каждую среду",
  "FREQ=WEEKLY;BYDAY=TH": "каждый четверг",
  "FREQ=WEEKLY;BYDAY=FR": "каждую пятницу",
  "FREQ=WEEKLY;BYDAY=SA": "каждую субботу",
  "FREQ=WEEKLY;BYDAY=SU": "каждое воскресенье",
  "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR": "по будням",
  "FREQ=WEEKLY;BYDAY=SA,SU": "по выходным",
  "FREQ=DAILY": "каждый день",
  "FREQ=WEEKLY": "каждую неделю",
  "FREQ=MONTHLY": "каждый месяц",
};

export function formatRRule(rrule: string | null | undefined): string {
  if (!rrule) return "";
  const clean = rrule.trim().toUpperCase().replace(/^RRULE:/, "");
  if (RRULE_RU_MAP[clean]) {
    return RRULE_RU_MAP[clean];
  }
  if (clean.includes("FREQ=DAILY")) return "каждый день";
  if (clean.includes("FREQ=WEEKLY")) return "еженедельно";
  if (clean.includes("FREQ=MONTHLY")) return "ежемесячно";
  return clean;
}

