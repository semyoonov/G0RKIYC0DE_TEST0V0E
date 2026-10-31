import type { AssistantEvent } from "../types";

const DAY_MS = 86_400_000;
const WEEKDAY_CODES = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"];

export interface GanttRow {
  event: AssistantEvent;
  /** Calendar days the event lands on inside the visible window, ascending. */
  days: string[];
}

/** Calendar day ("YYYY-MM-DD") of an instant, as the account sees it. */
export function dayKeyOf(value: string | Date, timezone: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: timezone,
  }).formatToParts(date);
  const fields: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") fields[part.type] = part.value;
  }
  return `${fields.year}-${fields.month}-${fields.day}`;
}

export function dayNumber(key: string): number {
  const [year, month, day] = key.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

export function addDays(key: string, days: number): string {
  return new Date(dayNumber(key) + days * DAY_MS).toISOString().slice(0, 10);
}

export function buildDayWindow(startKey: string, days: number): string[] {
  return Array.from({ length: days }, (_, index) => addDays(startKey, index));
}

export function weekdayCode(key: string): string {
  return WEEKDAY_CODES[new Date(dayNumber(key)).getUTCDay()];
}

function parseRule(rrule: string): { freq: string; byday: string[] } {
  const clean = rrule.trim().toUpperCase().replace(/^RRULE:/, "");
  const fields = new Map<string, string>();
  for (const chunk of clean.split(";")) {
    const [key, value] = chunk.split("=");
    if (key && value) fields.set(key.trim(), value.trim());
  }
  const freq = fields.get("FREQ") ?? "WEEKLY";
  const byday = (fields.get("BYDAY") ?? "")
    .split(",")
    .map((code) => code.slice(-2))
    .filter((code) => WEEKDAY_CODES.includes(code));
  return { freq, byday };
}

/** The day the event itself is anchored to, or an empty string for undated records. */
export function anchorDay(event: AssistantEvent, timezone: string): string {
  const source = event.starts_at ?? event.remind_at;
  return source ? dayKeyOf(source, timezone) : "";
}

/**
 * Days an event is visible on inside `[startKey, endKey]`.
 *
 * Recurrence is expanded on calendar days rather than timestamps: the rule's
 * weekday and the first occurrence carry the meaning, and a wall-clock shift of
 * one hour must not move a weekly meeting into another day.
 */
export function eventDays(
  event: AssistantEvent,
  timezone: string,
  startKey: string,
  endKey: string,
): string[] {
  const first = anchorDay(event, timezone);
  if (!first) return [];
  if (!event.rrule) return first >= startKey && first <= endKey ? [first] : [];

  const { freq, byday } = parseRule(event.rrule);
  const firstNumber = dayNumber(first);
  const firstDayOfMonth = Number(first.slice(8, 10));
  const windowStart = Math.max(firstNumber, dayNumber(startKey));
  const windowEnd = dayNumber(endKey);
  const days: string[] = [];

  for (let value = windowStart; value <= windowEnd; value += DAY_MS) {
    const key = new Date(value).toISOString().slice(0, 10);
    if (freq === "DAILY") {
      days.push(key);
    } else if (freq === "MONTHLY") {
      if (Number(key.slice(8, 10)) === firstDayOfMonth) days.push(key);
    } else {
      const weekday = weekdayCode(key);
      const matches = byday.length > 0 ? byday.includes(weekday) : weekday === weekdayCode(first);
      if (matches) days.push(key);
    }
  }
  return days;
}

export function buildRows(
  events: AssistantEvent[],
  timezone: string,
  startKey: string,
  endKey: string,
): { rows: GanttRow[]; undated: AssistantEvent[] } {
  const rows: GanttRow[] = [];
  const undated: AssistantEvent[] = [];
  for (const event of events) {
    if (!anchorDay(event, timezone)) {
      undated.push(event);
      continue;
    }
    const days = eventDays(event, timezone, startKey, endKey);
    if (days.length > 0) rows.push({ event, days });
  }
  rows.sort((left, right) => {
    const [first] = left.days;
    const [second] = right.days;
    return first === second ? left.event.id - right.event.id : first.localeCompare(second);
  });
  return { rows, undated };
}

export function dayLabel(key: string): { day: string; weekday: string; month: string } {
  const date = new Date(dayNumber(key));
  return {
    day: String(date.getUTCDate()).padStart(2, "0"),
    weekday: new Intl.DateTimeFormat("ru-RU", { weekday: "short", timeZone: "UTC" }).format(date),
    month: new Intl.DateTimeFormat("ru-RU", { month: "long", timeZone: "UTC" }).format(date),
  };
}
