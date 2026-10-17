import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AssistantEvent } from "../types";
import { EventCard } from "./EventCard";

function makeEvent(overrides: Partial<AssistantEvent> = {}): AssistantEvent {
  return {
    id: 7,
    user_id: 1,
    type: "reminder",
    title: "Позвонить Ивану",
    description: null,
    starts_at: "2025-03-04T10:00:00Z",
    remind_at: "2025-03-04T10:00:00Z",
    status: "pending",
    source: "web",
    created_at: "2025-03-03T09:00:00Z",
    updated_at: "2025-03-03T09:00:00Z",
    ...overrides,
  };
}

describe("EventCard", () => {
  it("renders type, status and time and completes a pending event", async () => {
    const onComplete = vi.fn().mockResolvedValue(undefined);
    render(<EventCard event={makeEvent()} timezone="Europe/Moscow" onComplete={onComplete} />);

    expect(screen.getByText("напоминание")).toBeInTheDocument();
    expect(screen.getByText("не выполнено")).toBeInTheDocument();
    expect(screen.getByText("Позвонить Ивану")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "выполнено" }));

    expect(onComplete).toHaveBeenCalledWith(7);
  });

  it("hides the completion action for finished events", () => {
    render(
      <EventCard event={makeEvent({ status: "done" })} timezone="Europe/Moscow" onComplete={() => {}} />,
    );

    expect(screen.getByText("выполнено")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "выполнено" })).not.toBeInTheDocument();
  });

  it("reports a failed completion on the card", async () => {
    const onComplete = vi.fn().mockRejectedValue(new Error("boom"));
    render(<EventCard event={makeEvent()} timezone="Europe/Moscow" onComplete={onComplete} />);

    await userEvent.click(screen.getByRole("button", { name: "выполнено" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось отметить выполненной.");
  });
});
