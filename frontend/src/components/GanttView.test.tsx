import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantEvent } from "../types";
import { GanttView } from "./GanttView";

const api = vi.hoisted(() => ({
  fetchEvents: vi.fn(),
  completeEvent: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, fetchEvents: api.fetchEvents, completeEvent: api.completeEvent };
});

const DAY_MS = 86_400_000;

function inDays(days: number, hour = 10): string {
  const date = new Date(Date.now() + days * DAY_MS);
  date.setUTCHours(hour, 0, 0, 0);
  return date.toISOString();
}

function makeEvent(overrides: Partial<AssistantEvent> = {}): AssistantEvent {
  return {
    id: 1,
    user_id: 1,
    type: "meeting",
    title: "Созвон по макету",
    description: null,
    starts_at: inDays(1),
    remind_at: null,
    rrule: null,
    status: "pending",
    source: "web",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  api.fetchEvents.mockReset();
  api.completeEvent.mockReset();
  api.fetchEvents.mockResolvedValue([
    makeEvent({ id: 1, title: "Созвон по макету", starts_at: inDays(1, 10) }),
    makeEvent({ id: 2, title: "Написать отчёт", type: "task", starts_at: inDays(3, 18) }),
    makeEvent({
      id: 3,
      title: "Планёрка команды",
      starts_at: inDays(2, 9),
      rrule: "FREQ=WEEKLY;BYDAY=MO",
    }),
    makeEvent({ id: 4, title: "Без даты задача", type: "task", starts_at: null }),
  ]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("GanttView", () => {
  it("показывает события, дни периода и задачи без даты", async () => {
    render(<GanttView timezone="Europe/Moscow" onSwitchToChat={() => {}} />);

    expect(await screen.findByText("Созвон по макету")).toBeInTheDocument();
    expect(screen.getByText("Написать отчёт")).toBeInTheDocument();
    expect(screen.getByText("Без даты (1)")).toBeInTheDocument();
    expect(screen.getByText("Без даты задача")).toBeInTheDocument();
    expect(screen.getByText(/Задачи и встречи/)).toBeInTheDocument();
    expect(api.fetchEvents).toHaveBeenCalledWith("all");
  });

  it("открывает детали по клику на полосу и отмечает выполнение", async () => {
    const user = userEvent.setup();
    const onEventCompleted = vi.fn();
    api.completeEvent.mockResolvedValue(undefined);
    render(
      <GanttView timezone="Europe/Moscow" onSwitchToChat={() => {}} onEventCompleted={onEventCompleted} />,
    );

    await screen.findByText("Созвон по макету");
    const bar = document.querySelector<HTMLButtonElement>('[data-gantt-bar="1"]');
    expect(bar).not.toBeNull();
    await user.click(bar as HTMLButtonElement);

    expect(screen.getAllByText("Созвон по макету").length).toBeGreaterThan(1);
    await user.click(screen.getByRole("button", { name: /Выполнено/ }));

    await waitFor(() => expect(api.completeEvent).toHaveBeenCalledWith(1));
    expect(onEventCompleted).toHaveBeenCalledWith(1);
    expect(api.fetchEvents).toHaveBeenCalledTimes(2);
  });

  it("фильтрует по типу и по выполненным", async () => {
    const user = userEvent.setup();
    render(<GanttView timezone="Europe/Moscow" onSwitchToChat={() => {}} />);

    await screen.findByText("Созвон по макету");
    await user.click(screen.getByRole("button", { name: /Задачи/ }));

    expect(screen.getByText("Написать отчёт")).toBeInTheDocument();
    expect(screen.queryByText("Созвон по макету")).not.toBeInTheDocument();
  });

  it("предлагает запланировать через чат, когда период пуст", async () => {
    const user = userEvent.setup();
    const onSwitchToChat = vi.fn();
    api.fetchEvents.mockResolvedValue([]);
    render(<GanttView timezone="Europe/Moscow" onSwitchToChat={onSwitchToChat} />);

    expect(await screen.findByText("На этот период ничего не запланировано.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Запланировать через чат/ }));

    expect(onSwitchToChat).toHaveBeenCalled();
  });

  it("жалуется, если задачи не загрузились", async () => {
    api.fetchEvents.mockRejectedValue(new Error("offline"));
    render(<GanttView timezone="Europe/Moscow" onSwitchToChat={() => {}} />);

    expect(await screen.findByText(/Не удалось загрузить задачи/)).toBeInTheDocument();
  });
});
