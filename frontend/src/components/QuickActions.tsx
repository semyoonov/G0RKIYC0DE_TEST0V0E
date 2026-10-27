import { useEffect, useRef, useState } from "react";

import { cn } from "../lib/utils";

interface QuickActionsProps {
  actions: string[];
  disabled: boolean;
  onSelect: (action: string) => void;
}

const FLASH_MS = 450;

export function QuickActions({ actions, disabled, onSelect }: QuickActionsProps) {
  // Нажатая кнопка коротко вспыхивает акцентом и плавно гаснет.
  const [flashed, setFlashed] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const select = (action: string) => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    setFlashed(action);
    timer.current = window.setTimeout(() => setFlashed(null), FLASH_MS);
    onSelect(action);
  };

  return (
    // Одна строка: если не влезает на узком экране — листается вбок, без переноса.
    <nav
      className="-mx-4 flex gap-1 overflow-x-auto sm:gap-1.5 px-4 [scrollbar-width:none] sm:mx-0 sm:px-0 [&::-webkit-scrollbar]:hidden"
      aria-label="Быстрые действия"
    >
      {actions.map((action) => (
        <button
          key={action}
          type="button"
          disabled={disabled}
          onClick={() => select(action)}
          className={cn(
            "h-7 shrink-0 whitespace-nowrap rounded-full border px-2 text-[10.5px] sm:px-2.5 sm:text-[11px] hover:border-accent/50 hover:text-ink disabled:pointer-events-none disabled:opacity-50",
            flashed === action
              ? "border-accent bg-accent text-white transition-none disabled:opacity-100"
              : "border-line bg-card text-ink-muted transition-[color,background-color,border-color,opacity] duration-500 ease-out",
          )}
        >
          {action}
        </button>
      ))}
    </nav>
  );
}
