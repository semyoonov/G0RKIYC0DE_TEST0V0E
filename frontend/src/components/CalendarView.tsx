import { useCallback, useEffect, useMemo, useState } from "react";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import rrulePlugin from "@fullcalendar/rrule";
import ruLocale from "@fullcalendar/core/locales/ru";
import {
  Bell,
  Calendar as CalendarIcon,
  Check,
  CheckSquare,
  Clock,
  Download,
  MessageSquare,
  RefreshCw,
  X,
} from "lucide-react";

import { completeEvent, downloadCalendarIcs, fetchEvents } from "../lib/api";
import { EVENT_STATUS_LABELS, EVENT_TYPE_LABELS, formatEventTime, formatRRule } from "../lib/format";
import type { AssistantEvent, EventType } from "../types";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

interface CalendarViewProps {
  timezone: string;
  onSwitchToChat: () => void;
  onEventCompleted?: (eventId: number) => void;
}

const TYPE_COLORS: Record<EventType, { bg: string; border: string; text: string }> = {
  meeting: {
    bg: "#1e3a8a",
    border: "#3b82f6",
    text: "#dbeafe",
  },
  task: {
    bg: "#334155",
    border: "#64748b",
    text: "#f1f5f9",
  },
  reminder: {
    bg: "#78350f",
    border: "#f59e0b",
    text: "#fef3c7",
  },
};

const DONE_COLOR = {
  bg: "#064e3b",
  border: "#10b981",
  text: "#d1fae5",
};

function eventDateKey(event: AssistantEvent): string {
  const raw = event.starts_at ?? event.remind_at ?? event.created_at;
  return raw.slice(0, 10);
}

function formatDateHeading(dateStr: string): string {
  try {
    const [y, m, d] = dateStr.split("-").map(Number);
    const date = new Date(y, m - 1, d);
    return new Intl.DateTimeFormat("ru-RU", {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(date);
  } catch {
    return dateStr;
  }
}

export function CalendarView({ timezone, onSwitchToChat, onEventCompleted }: CalendarViewProps) {
  const [events, setEvents] = useState<AssistantEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Фильтры
  const [typeFilter, setTypeFilter] = useState<"all" | EventType>("all");
  const [hideDone, setHideDone] = useState(false);
  const [recurringOnly, setRecurringOnly] = useState(false);

  // Выбранная дата для детального просмотра
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [completingId, setCompletingId] = useState<number | null>(null);
  const [exportingIcs, setExportingIcs] = useState(false);
  const [exportSuccess, setExportSuccess] = useState(false);

  const handleExportIcs = async () => {
    setExportingIcs(true);
    try {
      await downloadCalendarIcs();
      setExportSuccess(true);
      setTimeout(() => setExportSuccess(false), 3000);
    } catch {
      setError("Не удалось экспортировать .ics файл календаря.");
    } finally {
      setExportingIcs(false);
    }
  };

  const loadEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEvents("all");
      setEvents(data);
    } catch (err) {
      setError("Не удалось загрузить события. Попробуйте обновить.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  const handleComplete = async (eventId: number) => {
    setCompletingId(eventId);
    try {
      const updated = await completeEvent(eventId);
      setEvents((prev) => prev.map((ev) => (ev.id === eventId ? updated : ev)));
      if (onEventCompleted) onEventCompleted(eventId);
    } catch (err) {
      // Игнорируем или оставляем прежнее состояние при ошибке
    } finally {
      setCompletingId(null);
    }
  };

  // Фильтрованные события
  const filteredEvents = useMemo(() => {
    return events.filter((ev) => {
      if (typeFilter !== "all" && ev.type !== typeFilter) return false;
      if (hideDone && ev.status === "done") return false;
      if (recurringOnly && !ev.rrule) return false;
      return true;
    });
  }, [events, typeFilter, hideDone, recurringOnly]);

  // Статистика
  const stats = useMemo(() => {
    const total = events.length;
    const meetings = events.filter((e) => e.type === "meeting").length;
    const tasks = events.filter((e) => e.type === "task").length;
    const reminders = events.filter((e) => e.type === "reminder").length;
    const done = events.filter((e) => e.status === "done").length;
    const recurring = events.filter((e) => Boolean(e.rrule)).length;
    return { total, meetings, tasks, reminders, done, recurring };
  }, [events]);

  // Преобразование в формат FullCalendar
  const calendarEvents = useMemo(() => {
    return filteredEvents.map((ev) => {
      const isDone = ev.status === "done";
      const colors = isDone ? DONE_COLOR : TYPE_COLORS[ev.type];
      const hasTime = Boolean(ev.starts_at);
      const start = ev.starts_at || ev.remind_at || ev.created_at;

      const baseEvent = {
        id: String(ev.id),
        title: ev.rrule ? `🔄 ${ev.title}` : ev.title,
        allDay: !hasTime,
        backgroundColor: colors.bg,
        borderColor: colors.border,
        textColor: colors.text,
        extendedProps: { event: ev },
      };

      if (ev.rrule) {
        const clean = ev.rrule.trim().replace(/^RRULE:/i, "");
        const iso = start ? start.replace(/[-:]/g, "").slice(0, 15) : "";
        return {
          ...baseEvent,
          rrule: iso ? `DTSTART:${iso}Z\nRRULE:${clean}` : `RRULE:${clean}`,
          duration: ev.type === "meeting" ? "00:30" : "00:15",
        };
      }

      return {
        ...baseEvent,
        start,
      };
    });
  }, [filteredEvents]);

  // События на выбранную дату
  const eventsOnSelectedDate = useMemo(() => {
    if (!selectedDate) return [];
    return events.filter((ev) => eventDateKey(ev) === selectedDate);
  }, [events, selectedDate]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-canvas">
      {/* Верхняя панель фильтров и статистики */}
      <div className="border-b border-line/70 bg-panel/70 px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Фильтры по типам событий */}
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
              Все ({stats.total})
            </button>
            <button
              type="button"
              onClick={() => setTypeFilter("meeting")}
              className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                typeFilter === "meeting"
                  ? "bg-sky-600 text-white shadow-sm"
                  : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
              }`}
            >
              <CalendarIcon className="size-3" />
              <span>Встречи ({stats.meetings})</span>
            </button>
            <button
              type="button"
              onClick={() => setTypeFilter("task")}
              className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                typeFilter === "task"
                  ? "bg-slate-600 text-white shadow-sm"
                  : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
              }`}
            >
              <CheckSquare className="size-3" />
              <span>Задачи ({stats.tasks})</span>
            </button>
            <button
              type="button"
              onClick={() => setTypeFilter("reminder")}
              className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                typeFilter === "reminder"
                  ? "bg-amber-600 text-white shadow-sm"
                  : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
              }`}
            >
              <Bell className="size-3" />
              <span>Напоминания ({stats.reminders})</span>
            </button>
            {stats.recurring > 0 ? (
              <button
                type="button"
                onClick={() => setRecurringOnly((prev) => !prev)}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  recurringOnly
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "border border-line bg-card/60 text-ink-muted hover:border-line-hover hover:text-ink"
                }`}
              >
                <RefreshCw className="size-3" />
                <span>Повторяющиеся ({stats.recurring})</span>
              </button>
            ) : null}
          </div>

          {/* Правые опции: Скрыть выполненные, Экспорт в .ics и Обновить */}
          <div className="flex items-center gap-2">
            <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-muted hover:text-ink">
              <input
                type="checkbox"
                checked={hideDone}
                onChange={(e) => setHideDone(e.target.checked)}
                className="size-3.5 rounded border-line bg-card text-accent focus:ring-accent/40"
              />
              <span>Только активные</span>
            </label>

            <button
              type="button"
              onClick={() => void handleExportIcs()}
              disabled={exportingIcs || loading}
              title="Экспорт всех событий в календарный файл .ics (RFC 5545)"
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-all ${
                exportSuccess
                  ? "border-success/50 bg-success/15 text-success"
                  : "border-line bg-card/80 text-ink-muted hover:border-accent/50 hover:bg-accent/10 hover:text-ink"
              } disabled:opacity-50`}
            >
              <Download className={`size-3.5 ${exportingIcs ? "animate-bounce text-accent" : exportSuccess ? "text-success" : ""}`} />
              <span className="hidden sm:inline">
                {exportSuccess ? "Скачано!" : exportingIcs ? "Экспорт…" : "Экспорт .ics"}
              </span>
            </button>

            <button
              type="button"
              onClick={() => void loadEvents()}
              disabled={loading}
              title="Обновить список событий"
              className="inline-flex size-8 items-center justify-center rounded-lg border border-line bg-card text-ink-muted transition-colors hover:border-accent/50 hover:text-ink disabled:opacity-50"
            >
              <RefreshCw className={`size-3.5 ${loading ? "animate-spin text-accent" : ""}`} />
            </button>
          </div>
        </div>
      </div>

      {/* Ошибка при загрузке */}
      {error ? (
        <div className="mx-4 mt-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-2.5 text-xs text-danger sm:mx-6">
          {error}
        </div>
      ) : null}

      {/* Основная область с FullCalendar */}
      <div className="relative flex-1 overflow-y-auto p-3 sm:p-5">
        <div className="fullcalendar-custom h-full min-h-[580px] rounded-2xl border border-line/80 bg-card p-3 shadow-xl sm:p-4">
          <FullCalendar
            plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin, rrulePlugin]}
            initialView="dayGridMonth"
            headerToolbar={{
              left: "prev,next today",
              center: "title",
              right: "dayGridMonth,timeGridWeek,timeGridDay",
            }}
            locale={ruLocale}
            events={calendarEvents}
            height="100%"
            dayMaxEvents={3}
            displayEventTime={false}
            selectable={true}
            dateClick={(info) => {
              setSelectedDate(info.dateStr);
              setSelectedEventId(null);
            }}
            eventClick={(info) => {
              const ev = info.event.extendedProps.event as AssistantEvent;
              setSelectedDate(eventDateKey(ev));
              setSelectedEventId(ev.id);
            }}
          />
        </div>
      </div>

      {/* Модальная панель просмотра событий выбранной даты */}
      {selectedDate ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          onClick={() => setSelectedDate(null)}
        >
          <div
            className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-line bg-panel shadow-2xl shadow-black/80 animate-in fade-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Заголовок модалки */}
            <div className="flex items-center justify-between border-b border-line/70 px-5 py-4">
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-wider text-accent">События на дату</p>
                <h2 className="text-base font-semibold capitalize text-ink">
                  {formatDateHeading(selectedDate)}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDate(null)}
                className="inline-flex size-8 items-center justify-center rounded-lg border border-line bg-card text-ink-muted transition-colors hover:border-line-hover hover:text-ink"
                title="Закрыть"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Список событий на этот день */}
            <div className="flex-1 space-y-3 overflow-y-auto p-5">
              {eventsOnSelectedDate.length === 0 ? (
                <div className="py-8 text-center">
                  <CalendarIcon className="mx-auto size-10 text-ink-dim/40" />
                  <p className="mt-2 text-sm text-ink-muted">На эту дату пока нет запланированных событий.</p>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSelectedDate(null);
                      onSwitchToChat();
                    }}
                    className="mt-4 gap-2 text-xs"
                  >
                    <MessageSquare className="size-3.5" />
                    <span>Запланировать через чат</span>
                  </Button>
                </div>
              ) : (
                eventsOnSelectedDate.map((ev) => {
                  const isDone = ev.status === "done";
                  const isSelected = selectedEventId === ev.id;
                  const isBusy = completingId === ev.id;
                  const time = formatEventTime(ev.starts_at ?? ev.remind_at, timezone);

                  return (
                    <article
                      key={ev.id}
                      className={`group relative rounded-xl border p-3.5 transition-all ${
                        isSelected
                          ? "border-accent ring-2 ring-accent/30 bg-card"
                          : "border-line/80 bg-card hover:border-line-hover"
                      } ${isDone ? "opacity-75" : ""}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5">
                          {ev.type === "meeting" ? (
                            <Badge variant="accent" className="gap-1 px-2 py-0.5 text-[11px]">
                              <CalendarIcon className="size-3" />
                              <span>{EVENT_TYPE_LABELS.meeting}</span>
                            </Badge>
                          ) : ev.type === "reminder" ? (
                            <Badge variant="warning" className="gap-1 px-2 py-0.5 text-[11px]">
                              <Bell className="size-3" />
                              <span>{EVENT_TYPE_LABELS.reminder}</span>
                            </Badge>
                          ) : (
                            <Badge variant="neutral" className="gap-1 px-2 py-0.5 text-[11px]">
                              <CheckSquare className="size-3" />
                              <span>{EVENT_TYPE_LABELS.task}</span>
                            </Badge>
                          )}
                        </div>

                        <div className="flex items-center gap-1.5">
                          {ev.rrule ? (
                            <Badge variant="neutral" className="gap-1 border-accent/40 bg-accent/10 px-2 py-0.5 text-[11px] text-accent">
                              <RefreshCw className="size-2.5 text-accent" />
                              <span>{formatRRule(ev.rrule)}</span>
                            </Badge>
                          ) : null}
                          <Badge
                            variant={isDone ? "success" : ev.status === "cancelled" ? "danger" : "neutral"}
                            className="px-2 py-0.5 text-[11px]"
                          >
                            {isDone ? <Check className="mr-1 size-3" /> : null}
                            <span>{EVENT_STATUS_LABELS[ev.status]}</span>
                          </Badge>
                        </div>
                      </div>

                      <h3
                        className={`mt-2 text-sm font-medium ${
                          isDone ? "text-ink-muted line-through" : "text-ink"
                        }`}
                      >
                        {ev.title}
                      </h3>

                      {ev.description ? (
                        <p className="mt-1 text-xs text-ink-dim leading-relaxed">{ev.description}</p>
                      ) : null}

                      <div className="mt-3 flex items-center justify-between border-t border-line/40 pt-2.5">
                        {time ? (
                          <div className="inline-flex items-center gap-1 font-mono text-xs text-ink-muted">
                            <Clock className="size-3 text-ink-dim" />
                            <span>{time}</span>
                          </div>
                        ) : (
                          <span className="text-[11px] text-ink-dim">Весь день</span>
                        )}

                        {ev.status === "pending" ? (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isBusy}
                            onClick={() => void handleComplete(ev.id)}
                            className="h-7 gap-1 px-2.5 text-xs text-ink hover:text-accent"
                          >
                            <Check className="size-3 text-accent" />
                            <span>{isBusy ? "Секунду…" : "Выполнено"}</span>
                          </Button>
                        ) : null}
                      </div>
                    </article>
                  );
                })
              )}
            </div>

            {/* Подвал модалки */}
            <div className="flex items-center justify-between border-t border-line/70 bg-raised/40 px-5 py-3">
              <span className="text-xs text-ink-dim">
                Всего событий: {eventsOnSelectedDate.length}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setSelectedDate(null)}
                className="h-8 text-xs"
              >
                Закрыть
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
