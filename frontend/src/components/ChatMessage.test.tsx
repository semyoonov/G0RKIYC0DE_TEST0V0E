import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AssistantEvent, ChatReply } from "../types";
import { ChatMessage } from "./ChatMessage";

function makeEvent(id: number, title: string): AssistantEvent {
  return {
    id,
    user_id: 1,
    type: "task",
    title,
    description: null,
    starts_at: "2025-03-04T10:00:00Z",
    remind_at: null,
    status: "pending",
    source: "web",
    created_at: "2025-03-03T09:00:00Z",
    updated_at: "2025-03-03T09:00:00Z",
  };
}

function makeReply(overrides: Partial<ChatReply> = {}): ChatReply {
  return {
    reply: "Создал задачу «Купить билеты».",
    audio: null,
    audio_mime: null,
    events: [makeEvent(1, "Купить билеты")],
    needs_clarification: false,
    intent: "create_task",
    ...overrides,
  };
}

describe("ChatMessage", () => {
  it("shows the action label and cards for a create action", () => {
    render(
      <ChatMessage
        entry={{ id: "m1", role: "assistant", reply: makeReply() }}
        timezone="Europe/Moscow"
        onComplete={() => {}}
      />,
    );

    expect(screen.getByText("Создано")).toBeInTheDocument();
    expect(screen.getByText("Купить билеты")).toBeInTheDocument();
  });

  it("keeps only the label after a delete action", () => {
    render(
      <ChatMessage
        entry={{ id: "m2", role: "assistant", reply: makeReply({ intent: "delete_event" }) }}
        timezone="Europe/Moscow"
        onComplete={() => {}}
      />,
    );

    expect(screen.getByText("Удалено")).toBeInTheDocument();
    expect(screen.queryByText("Купить билеты")).not.toBeInTheDocument();
  });

  it("renders user and error entries", () => {
    const { rerender } = render(
      <ChatMessage entry={{ id: "m3", role: "user", text: "Что у меня сегодня?" }} timezone="Europe/Moscow" onComplete={() => {}} />,
    );
    expect(screen.getByText("Что у меня сегодня?")).toBeInTheDocument();

    rerender(<ChatMessage entry={{ id: "m4", role: "error", text: "Не получилось" }} timezone="Europe/Moscow" onComplete={() => {}} />);
    expect(screen.getByText("Не получилось")).toBeInTheDocument();
  });
});
