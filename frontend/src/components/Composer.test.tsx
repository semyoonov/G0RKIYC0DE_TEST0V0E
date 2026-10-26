import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

describe("Composer conversation mode", () => {
  it("shows the listening button and an explicit stop button", () => {
    const onToggleRecording = vi.fn();
    render(
      <Composer
        disabled={false}
        recording
        busy={false}
        conversationActive
        conversationPhase="listening"
        onSend={() => {}}
        onToggleRecording={onToggleRecording}
      />,
    );

    expect(screen.getByText("Слушаю…")).toBeInTheDocument();
    expect(screen.getByText("Стоп")).toBeInTheDocument();
    expect(screen.queryByText("Отправить")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Сообщение")).toBeDisabled();

    fireEvent.click(screen.getByText("Стоп"));
    expect(onToggleRecording).toHaveBeenCalledTimes(1);
  });

  it("keeps the one-shot controls when the mode is idle", () => {
    render(
      <Composer
        disabled={false}
        recording={false}
        busy={false}
        conversationActive={false}
        onSend={() => {}}
        onToggleRecording={() => {}}
      />,
    );

    expect(screen.getByText("Голосом")).toBeInTheDocument();
    expect(screen.getByText("Отправить")).toBeInTheDocument();
    expect(screen.getByLabelText("Сообщение")).not.toBeDisabled();
  });
});
