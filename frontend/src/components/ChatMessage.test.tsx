import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantEvent, ChatReply } from "../types";
import { ChatMessage } from "./ChatMessage";

beforeEach(() => {
  // jsdom has no object URLs; the audio element only needs a stable source.
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(() => "blob:reply"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    writable: true,
    value: vi.fn(),
  });
});

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

  it("renders reply audio that appears after the entry was created", () => {
    const entry = { id: "m5", role: "assistant" as const, reply: makeReply() };
    const onReplyAudioEnd = vi.fn();
    const { rerender } = render(
      <ChatMessage
        entry={entry}
        timezone="Europe/Moscow"
        autoPlayAudio={false}
        onComplete={() => {}}
        onReplyAudioEnd={onReplyAudioEnd}
      />,
    );

    expect(screen.queryByText("Прослушать ответ")).not.toBeInTheDocument();
    expect(onReplyAudioEnd).not.toHaveBeenCalled();

    rerender(
      <ChatMessage
        entry={{ ...entry, audio: { data: "QUJD", mime: "audio/ogg" } }}
        timezone="Europe/Moscow"
        autoPlayAudio={false}
        onComplete={() => {}}
        onReplyAudioEnd={onReplyAudioEnd}
      />,
    );

    expect(screen.getByText("Прослушать ответ")).toBeInTheDocument();
    expect(onReplyAudioEnd).toHaveBeenCalledWith("m5");
  });

  it("shows that the answer is being voiced while speech is generated", () => {
    const entry = { id: "m6", role: "assistant" as const, reply: makeReply() };
    const { rerender } = render(
      <ChatMessage
        entry={entry}
        timezone="Europe/Moscow"
        autoPlayAudio={false}
        synthesizing
        onComplete={() => {}}
      />,
    );

    expect(screen.getByText("Озвучиваю ответ…")).toBeInTheDocument();

    rerender(
      <ChatMessage
        entry={{ ...entry, audio: { data: "QUJD", mime: "audio/ogg" } }}
        timezone="Europe/Moscow"
        autoPlayAudio={false}
        synthesizing={false}
        onComplete={() => {}}
      />,
    );

    expect(screen.queryByText("Озвучиваю ответ…")).not.toBeInTheDocument();
    expect(screen.getByText("Прослушать ответ")).toBeInTheDocument();
  });
});
