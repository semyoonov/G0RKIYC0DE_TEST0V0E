import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Bell, Calendar as CalendarIcon, Check, CheckSquare, ChevronLeft, ChevronRight, MessageSquare, RefreshCw, X } from "lucide-react";

import { completeEvent, fetchEvents } from "../lib/api";
import { EVENT_TYPE_LABELS, formatEventTime, formatRRule } from "../lib/format";
import { addDays, buildDayWindow, buildRows, dayKeyOf, dayLabel, weekdayCode } from "../lib/gantt";
import type { AssistantEvent, EventType } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

interface GanttViewProps {
  timezone: string;
  onSwitchToChat: () => void;
  onEventCompleted?: (eventId: number) => void;
}

const WINDOW_OPTIONS = [
  { days: 14, label: "2 недели" },
  { days: 30, label: "Месяц" },
] as const;

const TYPE_STYLES: Record<EventType, { bar: string; dot: string; chip: string }> = {
  meeting: {
    bar: "border-sky-400/70 bg-sky-600/80 text-white",
    dot: "bg-sky-400",
    chip: "bg-sky-600 text-white",
  },
  task: {
    bar: "border-slate-400/60 bg-slate-600/80 text-white",
    dot: "bg-slate-400",
    chip: "bg-slate-600 text-white",
  },
  reminder: {
    bar: "border-amber-400/70 bg-amber-600/80 text-white",
    dot: "bg-amber-400",
    chip: "bg-amber-600 text-white",
  },
};

const DONE_BAR = "border-emerald-500/60 bg-emerald-800/60 text-emerald-100 line-through";

const TYPE_FILTER_LABELS: Record<EventType, string> = {
  meeting: "Встречи",
  task: "Задачи",
  reminder: "Напоминания",
};

const TYPE_ICONS: Record<EventType, typeof Bell> = {
  meeting: CalendarIcon,
  task: CheckSquare,
  reminder: Bell,
};

function dayTimeLabel(event: AssistantEvent, timezone: string): string {
  if (!event.starts_at && !event.remind_at) return "без времени";
  const moment = event.starts_at ?? event.remind_at;
  return new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit", timeZone: timezone }).format(
    new Date(moment as string),
  );
}

export function GanttView({ timezone, onSwitchToChat, onEventCompleted }: GanttViewProps) {
  const [events, setEvents] = useState<AssistantEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<"all" | EventType>("all");
  const [hideDone, setHideDone] = useState(false);
  const [windowDays, setWindowDays] = useState<number>(WINDOW_OPTIONS[0].days);
  const [anchor, setAnchor] = useState(() => dayKeyOf(new Date(), timezone));
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [completingId, setCompletingId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvents(await fetchEvents("all"));
    } catch {
      setError("Не удалось загрузить задачи. Попробуйте обновить.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  const days = useMemo(() => buildDayWindow(anchor, windowDays), [anchor, windowDays]);
  const rangeEnd = days[days.length - 1] ?? anchor;
  const today = dayKeyOf(new Date(), timezone);

  const visible = useMemo(
    () =>
      events.filter((event) => {
        if (typeFilter !== "all" && event.type !== typeFilter) return false;
        if (hideDone && event.status !== "pending") return false;
        return true;
      }),
    [events, typeFilter, hideDone],
  );

  const { rows, undated } = useMemo(
    () => buildRows(visible, timezone, anchor, rangeEnd),
    [visible, timezone, anchor, rangeEnd],
  );

  const counts = useMemo(
    () => ({
      meeting: events.filter((event) => event.type === "meeting").length,
      task: events.filter((event) => event.type === "task").length,
      reminder: events.filter((event) => event.type === "reminder").length,
    }),
    [events],
  );

  const selected = useMemo(
    () => events.find((event) => event.id === selectedId) ?? null,
    [events, selectedId],
  );

  const handleComplete = async (eventId: number) => {
    setCompletingId(eventId);
    try {
      await completeEvent(eventId);
      onEventCompleted?.(eventId);
      await loadEvents();
    } catch {
      setError("Не удалось отметить выполнение. Попробуйте ещё раз.");
    } finally {
      setCompletingId(null);
    }
  };

  const scrollToDay = useCallback(
    (day: string, behavior: ScrollBehavior = "smooth") => {
      const container = scrollRef.current;
      const timeline = container?.querySelector<HTMLElement>(".gantt-timeline");
      const index = days.indexOf(day);
      if (!container || !timeline || index < 0) return;
      const dayWidth = timeline.offsetWidth / days.length;
      container.scrollTo({ left: Math.max(0, index * dayWidth - 24), behavior });
    },
    [days],
  );

  const shift = (deltaDays: number) => setAnchor((current) => addDays(current, deltaDays));
  const resetToToday = () => {
    setAnchor(today);
    scrollToDay(today);
  };

  const firstLabel = dayLabel(days[0] ?? anchor);
  const lastLabel = dayLabel(rangeEnd);
  const rangeTitle = `${firstLabel.day} ${firstLabel.month} — ${lastLabel.day} ${lastLabel.month} ${rangeEnd.slice(0, 4)}`;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-canvas">
      <div className="border-b border-line/70 bg-panel/70 px-4 py-3 sm:px-6 xl:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setTypeFilter("all")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                typeFilter === "all"
                  ? "bg-accent text-white shadow-sm"
                  : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
              }`}
            >
              Все ({events.length})
            </button>
            {(["meeting", "task", "reminder"] as const).map((type) => {
              const Icon = TYPE_ICONS[type];
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => setTypeFilter(type)}
                  className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                    typeFilter === type
                      ? `${TYPE_STYLES[type].chip} shadow-sm`
                      : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
                  }`}
                >
                  <Icon className="size-3" />
                  <span>
                    {TYPE_FILTER_LABELS[type]} ({counts[type]})
                  </span>
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-muted hover:text-ink">
              <input
                type="checkbox"
                checked={hideDone}
                onChange={(event) => setHideDone(event.target.checked)}
                className="size-3.5 rounded border-line bg-card text-accent focus:ring-accent/40"
              />
              <span>Только активные</span>
            </label>

            <div className="flex items-center rounded-lg border border-line bg-card/80 p-0.5">
              {WINDOW_OPTIONS.map((option) => (
                <button
                  key={option.days}
                  type="button"
                  onClick={() => setWindowDays(option.days)}
                  className={`rounded-md px-2 py-0.5 text-xs font-medium transition-colors ${
                    windowDays === option.days ? "bg-raised text-ink" : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => shift(-7)}
                title="Предыдущая неделя"
                className="inline-flex size-7 items-center justify-center rounded-lg border border-line bg-card/80 text-ink-muted transition-colors hover:border-line-hover hover:text-ink"
              >
                <ChevronLeft className="size-4" />
              </button>
              <button
                type="button"
                onClick={resetToToday}
                className="rounded-lg border border-line bg-card/80 px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:border-accent/50 hover:text-ink"
              >
                Сегодня
              </button>
              <button
                type="button"
                onClick={() => shift(7)}
                title="Следующая неделя"
                className="inline-flex size-7 items-center justify-center rounded-lg border border-line bg-card/80 text-ink-muted transition-colors hover:border-line-hover hover:text-ink"
              >
                <ChevronRight className="size-4" />
              </button>
              <button
                type="button"
                onClick={() => void loadEvents()}
                disabled={loading}
                title="Обновить"
                className="inline-flex size-7 items-center justify-center rounded-lg border border-line bg-card/80 text-ink-muted transition-colors hover:border-accent/50 hover:text-ink disabled:opacity-50"
              >
                <RefreshCw className={`size-3.5 ${loading ? "animate-spin text-accent" : ""}`} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {selected ? (
        <div className="mx-4 mt-3 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-card px-3 py-2.5 sm:mx-6 xl:mx-8">
          <Badge variant="accent">{EVENT_TYPE_LABELS[selected.type]}</Badge>
          <span className="text-sm font-medium text-ink">{selected.title}</span>
          <span className="text-xs text-ink-muted">{formatEventTime(selected.starts_at ?? selected.remind_at, timezone)}</span>
          {selected.rrule ? (
            <span className="inline-flex items-center gap-1 text-xs text-indigo-300">
              <RefreshCw className="size-3" />
              {formatRRule(selected.rrule)}
            </span>
          ) : null}
          {selected.description ? (
            <span className="min-w-0 flex-1 truncate text-xs text-ink-dim">{selected.description}</span>
          ) : (
            <span className="flex-1" />
          )}
          {selected.status === "pending" ? (
            <Button
              variant="outline"
              size="sm"
              disabled={completingId === selected.id}
              onClick={() => void handleComplete(selected.id)}
              className="gap-1 text-xs"
            >
              <Check className="size-3 text-accent" />
              <span>{completingId === selected.id ? "Секунду…" : "Выполнено"}</span>
            </Button>
          ) : (
            <Badge variant="success">выполнено</Badge>
          )}
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            title="Закрыть"
            className="inline-flex size-7 items-center justify-center rounded-lg border border-line text-ink-muted transition-colors hover:text-ink"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : null}

      {error ? (
        <div className="mx-4 mt-3 rounded-xl border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger sm:mx-6 xl:mx-8">
          {error}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          className="gantt-scroll h-full overflow-auto py-4"
          tabIndex={0}
          role="region"
          aria-label="Диаграмма Ганта: прокручивается по горизонтали"
        >
        {loading && events.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-ink-muted sm:px-6 xl:px-8" role="status">
            Загружаю задачи…
          </p>
        ) : rows.length === 0 && undated.length === 0 ? (
          <div className="px-4 py-12 text-center sm:px-6 xl:px-8">
            <CalendarIcon className="mx-auto size-10 text-ink-dim/40" />
            <p className="mt-3 text-sm text-ink-muted">На этот период ничего не запланировано.</p>
            <Button variant="secondary" size="sm" className="mt-4 gap-2" onClick={onSwitchToChat}>
              <MessageSquare className="size-3.5" />
              <span>Запланировать через чат</span>
            </Button>
          </div>
        ) : (
          <div className="gantt-grid" style={{ "--gantt-days": days.length } as CSSProperties}>
            <div className="sticky top-0 z-20 flex items-end border-b border-line/70 bg-canvas pb-1">
              <div className="gantt-label sticky left-0 z-10 shrink-0 bg-canvas pl-4 pr-3 sm:pl-6 xl:pl-8">
                <p className="text-xs uppercase tracking-wide text-ink-dim">Задачи и встречи</p>
                <p className="truncate text-sm font-medium capitalize text-ink">{rangeTitle}</p>
              </div>
              <div className="gantt-timeline flex">
                {days.map((day) => {
                  const label = dayLabel(day);
                  const isToday = day === today;
                  const isWeekend = ["SA", "SU"].includes(weekdayCode(day));
                  return (
                    <div
                      key={day}
                      className={`min-w-0 flex-1 rounded-t-md px-0.5 pb-1 text-center ${
                        isToday ? "bg-accent/10" : isWeekend ? "bg-panel/50" : ""
                      }`}
                    >
                      <span className={`block text-[10px] uppercase ${isToday ? "text-accent" : "text-ink-dim"}`}>
                        {label.weekday}
                      </span>
                      <span className={`block text-xs ${isToday ? "font-semibold text-accent" : "text-ink-muted"}`}>
                        {label.day}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {rows.map(({ event, days: eventDaysInWindow }) => {
              const done = event.status === "done";
              const cancelled = event.status === "cancelled";
              const Icon = TYPE_ICONS[event.type];
              const time = dayTimeLabel(event, timezone);
              return (
                <div key={event.id} className="flex items-stretch border-b border-line/40 last:border-b-0">
                  <button
                    type="button"
                    onClick={() => setSelectedId(event.id)}
                    className="gantt-label sticky left-0 z-10 flex min-w-0 shrink-0 items-center gap-2 bg-canvas py-2 pl-4 pr-3 text-left sm:pl-6 xl:pl-8"
                    title={event.title}
                  >
                    <span className={`size-1.5 shrink-0 rounded-full ${TYPE_STYLES[event.type].dot}`} />
                    <span className="min-w-0 flex-1">
                      <span
                        className={`flex items-center gap-1 text-sm ${done ? "text-ink-muted line-through" : "text-ink"} ${
                          cancelled ? "text-ink-dim line-through" : ""
                        }`}
                      >
                        <span className="truncate">{event.title}</span>
                        {event.rrule ? (
                          <RefreshCw className="size-3 shrink-0 text-indigo-300" aria-hidden="true" />
                        ) : null}
                      </span>
                      <span className="block text-[11px] text-ink-dim">
                        {event.rrule ? "каждую неделю · " : ""}
                        {time}
                      </span>
                    </span>
                  </button>

                  <div
                    className="gantt-timeline relative"
                    style={{
                      backgroundImage: "linear-gradient(to right, var(--color-line) 1px, transparent 1px)",
                      backgroundSize: `${100 / days.length}% 100%`,
                    }}
                  >
                    <div
                      className="pointer-events-none absolute inset-y-0 bg-accent/10"
                      style={{
                        left: `${(days.indexOf(today) / days.length) * 100}%`,
                        width: `${100 / days.length}%`,
                      }}
                      hidden={!days.includes(today)}
                    />
                    {eventDaysInWindow.map((day) => {
                      const index = days.indexOf(day);
                      if (index < 0) return null;
                      return (
                        <button
                          key={day}
                          type="button"
                          data-gantt-bar={event.id}
                          onClick={() => setSelectedId(event.id)}
                          title={`${time} — ${event.title}`}
                          className={`absolute inset-y-1 overflow-hidden rounded-md border px-1.5 text-left transition-transform hover:z-10 hover:scale-[1.02] ${
                            cancelled ? "border-line bg-raised text-ink-dim line-through" : done ? DONE_BAR : TYPE_STYLES[event.type].bar
                          }`}
                          style={{
                            left: `calc(${(index / days.length) * 100}% + 3px)`,
                            width: `calc(${100 / days.length}% - 6px)`,
                          }}
                        >
                          <span className="flex items-center gap-1 truncate text-[11px] font-medium">
                            <Icon className="size-3 shrink-0" aria-hidden="true" />
                            <span className="truncate">{time}</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {undated.length > 0 ? (
          <div className="mt-5 px-4 sm:px-6 xl:px-8">
            <p className="text-xs uppercase tracking-wide text-ink-dim">Без даты ({undated.length})</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {undated.map((event) => (
                <button
                  key={event.id}
                  type="button"
                  onClick={() => setSelectedId(event.id)}
                  className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs ${
                    event.status === "done"
                      ? "border-line bg-raised text-ink-dim line-through"
                      : "border-line bg-card text-ink hover:border-accent/50"
                  }`}
                >
                  <span className={`size-1.5 rounded-full ${TYPE_STYLES[event.type].dot}`} />
                  <span>{event.title}</span>
                </button>
              ))}
            </div>
          </div>
        ) : null}
        </div>
        <div className="pointer-events-none absolute inset-y-0 right-0 w-6 bg-gradient-to-l from-canvas to-transparent" />
      </div>

      <p className="border-t border-line/60 px-4 py-2 text-[11px] text-ink-dim sm:px-6 xl:px-8">
        Полоса — день события, метка — время. Повторяющиеся события показаны на каждом вхождении
        внутри периода. Период листается вбок: Shift+колесо или перетаскивание полосы прокрутки.
      </p>
    </div>
  );
}
