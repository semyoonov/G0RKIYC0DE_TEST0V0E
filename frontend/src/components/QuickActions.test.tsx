import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QuickActions } from "./QuickActions";

const ACTIONS = ["Что у меня сегодня?", "Что на завтра?", "Что на этой неделе?"];

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("QuickActions", () => {
  it("нажатая кнопка вспыхивает и сама гаснет", () => {
    render(<QuickActions actions={ACTIONS} disabled={false} onSelect={vi.fn()} />);
    const today = screen.getByRole("button", { name: "Что у меня сегодня?" });

    fireEvent.click(today);
    expect(today).toHaveClass("bg-accent");

    act(() => vi.advanceTimersByTime(1000));
    expect(today).not.toHaveClass("bg-accent");
  });

  it("при быстрых нажатиях подсвечена только последняя кнопка, и её вспышку не обрывает старый таймер", () => {
    const onSelect = vi.fn();
    render(<QuickActions actions={ACTIONS} disabled={false} onSelect={onSelect} />);
    const today = screen.getByRole("button", { name: "Что у меня сегодня?" });
    const tomorrow = screen.getByRole("button", { name: "Что на завтра?" });

    fireEvent.click(today);
    act(() => vi.advanceTimersByTime(300));
    fireEvent.click(tomorrow);
    act(() => vi.advanceTimersByTime(300));

    expect(today).not.toHaveClass("bg-accent");
    expect(tomorrow).toHaveClass("bg-accent");
    expect(onSelect.mock.calls).toEqual([["Что у меня сегодня?"], ["Что на завтра?"]]);
  });

  it("вспышка видна и тогда, когда после нажатия все кнопки блокируются", () => {
    const { rerender } = render(<QuickActions actions={ACTIONS} disabled={false} onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Что на завтра?" }));
    rerender(<QuickActions actions={ACTIONS} disabled onSelect={vi.fn()} />);

    const tomorrow = screen.getByRole("button", { name: "Что на завтра?" });
    expect(tomorrow).toBeDisabled();
    expect(tomorrow).toHaveClass("bg-accent", "disabled:opacity-100");
  });

  it("заблокированные кнопки не отправляют запрос и не вспыхивают", () => {
    const onSelect = vi.fn();
    render(<QuickActions actions={ACTIONS} disabled onSelect={onSelect} />);
    const today = screen.getByRole("button", { name: "Что у меня сегодня?" });

    fireEvent.click(today);
    expect(onSelect).not.toHaveBeenCalled();
    expect(today).not.toHaveClass("bg-accent");
  });

  it("размонтирование посреди вспышки не роняет React в ошибки", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = render(<QuickActions actions={ACTIONS} disabled={false} onSelect={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Что на этой неделе?" }));
    unmount();
    act(() => vi.advanceTimersByTime(1000));

    expect(consoleError).not.toHaveBeenCalled();
  });
});
