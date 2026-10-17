import { describe, expect, it } from "vitest";

import { formatEventTime } from "./format";

describe("formatEventTime", () => {
  const now = new Date("2025-03-03T10:00:00+03:00");

  it("uses relative day prefixes in the assistant timezone", () => {
    expect(formatEventTime("2025-03-03T12:00:00+03:00", "Europe/Moscow", now)).toBe("сегодня в 12:00");
    expect(formatEventTime("2025-03-04T10:00:00+03:00", "Europe/Moscow", now)).toBe("завтра в 10:00");
    expect(formatEventTime("2025-03-02T09:00:00+03:00", "Europe/Moscow", now)).toBe("вчера в 09:00");
  });

  it("formats later dates with a day and month", () => {
    expect(formatEventTime("2025-03-09T09:00:00+03:00", "Europe/Moscow", now)).toBe("09 марта в 09:00");
  });

  it("keeps the timezone of the assistant, not the viewer", () => {
    expect(formatEventTime("2025-03-03T12:00:00Z", "Europe/Moscow", now)).toBe("сегодня в 15:00");
  });

  it("returns an empty string without a date", () => {
    expect(formatEventTime(null, "Europe/Moscow", now)).toBe("");
    expect(formatEventTime("not-a-date", "Europe/Moscow", now)).toBe("");
  });
});
