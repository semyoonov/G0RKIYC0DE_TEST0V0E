import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReplyModeSwitch } from "./ReplyModeSwitch";

describe("ReplyModeSwitch", () => {
  it("marks the current mode as checked", () => {
    render(<ReplyModeSwitch speak onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "Голосом" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Текстом" })).toHaveAttribute("aria-checked", "false");
  });

  it("reports only an actual change of mode", () => {
    const onChange = vi.fn();
    render(<ReplyModeSwitch speak onChange={onChange} />);

    fireEvent.click(screen.getByRole("radio", { name: "Голосом" }));
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("radio", { name: "Текстом" }));
    expect(onChange).toHaveBeenCalledWith(false);
  });

  // role="radiogroup" обещает скринридеру и клавиатуре поведение радиокнопок (WAI-ARIA).
  it("переключается стрелками, как положено группе радиокнопок", () => {
    const onChange = vi.fn();
    render(<ReplyModeSwitch speak={false} onChange={onChange} />);

    fireEvent.keyDown(screen.getByRole("radio", { name: "Текстом" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("держит в порядке Tab только выбранный вариант", () => {
    render(<ReplyModeSwitch speak onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "Голосом" })).not.toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("radio", { name: "Текстом" })).toHaveAttribute("tabindex", "-1");
  });
});
