interface QuickActionsProps {
  actions: string[];
  disabled: boolean;
  onSelect: (action: string) => void;
}

export function QuickActions({ actions, disabled, onSelect }: QuickActionsProps) {
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Быстрые действия">
      {actions.map((action) => (
        <button
          key={action}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(action)}
          className="min-h-11 rounded-full border border-line bg-card px-3.5 py-2 text-xs text-ink-muted transition-colors hover:border-accent/50 hover:text-ink disabled:pointer-events-none disabled:opacity-50"
        >
          {action}
        </button>
      ))}
    </nav>
  );
}
