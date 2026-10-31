import { describe, expect, it } from "vitest";

import type { AssistantEvent } from "../types";
import {
  addDays,
  anchorDay,
  buildDayWindow,
  buildRows,
  dayKeyOf,
  dayLabel,
  dayNumber,
  eventDays,
  weekdayCode,
} from "./gantt";

function makeEvent(overrides: Partial<AssistantEvent> = {}): AssistantEvent {
  return {
    id: 1,
    user_id: 1,
    type: "meeting",
    title: "Созвон",
    description: null,
    starts_at: "2026-11-02T07:00:00Z",
    remind_at: null,
    rrule: null,
    status: "pending",
    source: "web",
    created_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-10-30T10:00:00Z",
    ...overrides,
  };
}

const TZ = "Europe/Moscow";
const START = "2026-11-02";
const END = "2026-11-15";

describe("day helpers", () => {
  it("keeps the account calendar day, not the browser one", () => {
    // 23:30 UTC is already the next day in Moscow.
    expect(dayKeyOf("2026-11-02T20:30:00Z", TZ)).toBe("2026-11-02");
    expect(dayKeyOf("2026-11-02T21:30:00Z", TZ)).toBe("2026-11-03");
    expect(dayKeyOf("2026-11-02T20:30:00Z", "UTC")).toBe("2026-11-02");
  });

  it("counts days across month and year boundaries", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(dayNumber("2026-11-02") - dayNumber("2026-11-01")).toBe(86_400_000);
  });

  it("labels a day without shifting it through the local timezone", () => {
    expect(buildDayWindow("2026-11-02", 3)).toEqual(["2026-11-02", "2026-11-03", "2026-11-04"]);
    expect(weekdayCode("2026-11-02")).toBe("MO");
    expect(dayLabel("2026-11-02")).toMatchObject({ day: "02", weekday: "пн", month: "ноябрь" });
  });
});

describe("eventDays", () => {
  it("keeps a single event on its own day inside the window", () => {
    expect(eventDays(makeEvent(), TZ, START, END)).toEqual(["2026-11-02"]);
    expect(eventDays(makeEvent(), TZ, "2026-11-05", END)).toEqual([]);
  });

  it("expands a weekly rule on every matching weekday", () => {
    const event = makeEvent({ starts_at: "2026-11-02T07:00:00Z", rrule: "FREQ=WEEKLY;BYDAY=MO" });

    expect(eventDays(event, TZ, START, END)).toEqual(["2026-11-02", "2026-11-09"]);
  });

  it("respects several weekdays and the first occurrence", () => {
    const event = makeEvent({ starts_at: "2026-11-03T07:00:00Z", rrule: "FREQ=WEEKLY;BYDAY=MO,TH" });

    expect(eventDays(event, TZ, START, END)).toEqual(["2026-11-05", "2026-11-09", "2026-11-12"]);
  });

  it("falls back to the start weekday when the rule has no BYDAY", () => {
    const event = makeEvent({ starts_at: "2026-11-04T07:00:00Z", rrule: "FREQ=WEEKLY" });

    expect(eventDays(event, TZ, START, END)).toEqual(["2026-11-04", "2026-11-11"]);
  });

  it("expands daily and monthly rules", () => {
    const daily = makeEvent({ starts_at: "2026-11-02T07:00:00Z", rrule: "FREQ=DAILY" });
    const monthly = makeEvent({ starts_at: "2026-11-02T07:00:00Z", rrule: "FREQ=MONTHLY" });

    expect(eventDays(daily, TZ, "2026-11-10", "2026-11-12")).toEqual([
      "2026-11-10",
      "2026-11-11",
      "2026-11-12",
    ]);
    expect(eventDays(monthly, TZ, "2026-11-01", "2026-12-31")).toEqual([
      "2026-11-02",
      "2026-12-02",
    ]);
  });

  it("uses the reminder time when a reminder has no start", () => {
    const event = makeEvent({ starts_at: null, remind_at: "2026-11-03T06:30:00Z" });

    expect(anchorDay(event, TZ)).toBe("2026-11-03");
    expect(eventDays(event, TZ, START, END)).toEqual(["2026-11-03"]);
  });
});

describe("buildRows", () => {
  it("sorts rows by first day and collects undated records apart", () => {
    const late = makeEvent({ id: 2, starts_at: "2026-11-09T07:00:00Z" });
    const early = makeEvent({ id: 3, starts_at: "2026-11-02T07:00:00Z" });
    const undated = makeEvent({ id: 4, starts_at: null, remind_at: null });

    const { rows, undated: withoutDate } = buildRows([late, undated, early], TZ, START, END);

    expect(rows.map((row) => row.event.id)).toEqual([3, 2]);
    expect(rows[1].days).toEqual(["2026-11-09"]);
    expect(withoutDate.map((event) => event.id)).toEqual([4]);
  });

  it("drops records that never land inside the window", () => {
    const past = makeEvent({ id: 5, starts_at: "2026-10-20T07:00:00Z" });

    expect(buildRows([past], TZ, START, END).rows).toEqual([]);
  });
});
