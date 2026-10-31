import { useCallback, useEffect, useRef, useState } from "react";

import {
  completeEvent,
  errorMessage,
  postChat,
  postSpeech,
  postVoice,
} from "../lib/api";
import type { ChatEntry, ChatReply } from "../types";

export interface ChatTurnResult {
  reply: ChatReply | null;
  error: string | null;
  /** true, если аудио пришло вместе с ответом или прикреплено после текста. */
  hasAudio: boolean;
}

export interface SendTextOptions {
  /** Запросить речь отдельным запросом и прикрепить её к показанному ответу. */
  speak?: boolean;
  closing?: boolean;
  voice?: string;
  /** Отменяет запрос речи; текстовый ответ сохраняется в любом случае. */
  signal?: AbortSignal;
  /** Отдаёт id реплики ассистента сразу после её добавления в чат. */
  onReplyEntry?: (entryId: string) => void;
  /** Синтез речи не удался, но текстовый ответ уже показан. */
  onSpeechError?: (message: string) => void;
}

export interface ChatController {
  entries: ChatEntry[];
  pending: boolean;
  status: string;
  /** Реплика ассистента, речь которой синтезируется прямо сейчас. */
  synthesizingEntryId: string | null;
  sendText: (text: string, options?: SendTextOptions) => Promise<ChatTurnResult>;
  sendVoice: (blob: Blob, options?: { voice?: string }) => Promise<void>;
  /** Прикрепляет речь к уже показанной реплике ассистента. */
  attachAudio: (entryId: string, audio: string, mime: string | null) => void;
  complete: (eventId: number) => Promise<void>;
  reportError: (message: string) => void;
}

function isAbort(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  return (error as { name?: string } | null)?.name === "AbortError";
}

export function useChat(): ChatController {
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  const [synthesizingEntryId, setSynthesizingEntryId] = useState<string | null>(null);
  const counter = useRef(0);

  const nextId = useCallback(() => {
    counter.current += 1;
    return `m${counter.current}`;
  }, []);

  const append = useCallback((entry: ChatEntry) => {
    setEntries((current) => [...current, entry]);
  }, []);

  const attachAudio = useCallback((entryId: string, audio: string, mime: string | null) => {
    if (!audio) return;
    setEntries((current) =>
      current.map((entry) =>
        entry.role === "assistant" && entry.id === entryId
          ? { ...entry, audio: { data: audio, mime } }
          : entry,
      ),
    );
  }, []);

  const sendText = useCallback(
    async (raw: string, options: SendTextOptions = {}): Promise<ChatTurnResult> => {
      const text = raw.trim();
      if (!text || pending) return { reply: null, error: null, hasAudio: false };
      append({ id: nextId(), role: "user", text });
      setPending(true);
      setStatus("Обрабатываю…");
      try {
        // Ответ запрашивается без озвучки, чтобы текст появился сразу.
        const reply = await postChat(text, {
          closing: options.closing ?? false,
          voice: options.voice ?? "",
        });
        const replyId = nextId();
        append({ id: replyId, role: "assistant", reply });
        options.onReplyEntry?.(replyId);

        if (options.speak !== true || !reply.reply) {
          return { reply, error: null, hasAudio: false };
        }
        if (reply.audio) return { reply, error: null, hasAudio: true };

        setSynthesizingEntryId(replyId);
        try {
          // Озвучивается ответ ассистента, а не фраза пользователя.
          const speech = await postSpeech(reply.reply, options.voice ?? "", options.signal);
          if (!speech.audio) return { reply, error: null, hasAudio: false };
          attachAudio(replyId, speech.audio, speech.audio_mime);
          return { reply, error: null, hasAudio: true };
        } catch (speechError) {
          if (!isAbort(speechError, options.signal)) {
            options.onSpeechError?.(errorMessage(speechError));
          }
          return { reply, error: null, hasAudio: false };
        } finally {
          setSynthesizingEntryId((current) => (current === replyId ? null : current));
        }
      } catch (error) {
        const message = errorMessage(error);
        append({ id: nextId(), role: "error", text: message });
        return { reply: null, error: message, hasAudio: false };
      } finally {
        setPending(false);
        setStatus("");
      }
    },
    [append, attachAudio, nextId, pending],
  );

  const sendVoice = useCallback(
    async (blob: Blob, options?: { voice?: string }) => {
      if (pending) return;
      append({ id: nextId(), role: "user", text: "Голосовое сообщение" });
      setPending(true);
      setStatus("Распознаю…");
      try {
        const reply = await postVoice(blob, options?.voice);
        append({ id: nextId(), role: "assistant", reply });
      } catch (error) {
        append({ id: nextId(), role: "error", text: errorMessage(error) });
      } finally {
        setPending(false);
        setStatus("");
      }
    },
    [append, nextId, pending],
  );

  const complete = useCallback(
    async (eventId: number) => {
      const updated = await completeEvent(eventId);
      setEntries((current) =>
        current.map((entry) => {
          if (entry.role !== "assistant") return entry;
          if (!entry.reply.events.some((event) => event.id === updated.id)) return entry;
          return {
            ...entry,
            reply: {
              ...entry.reply,
              events: entry.reply.events.map((event) => (event.id === updated.id ? updated : event)),
            },
          };
        }),
      );
    },
    [],
  );

  const reportError = useCallback(
    (message: string) => {
      append({ id: nextId(), role: "error", text: message });
    },
    [append, nextId],
  );

  useEffect(() => {
    return () => {
      counter.current = 0;
    };
  }, []);

  return {
    entries,
    pending,
    status,
    synthesizingEntryId,
    sendText,
    sendVoice,
    attachAudio,
    complete,
    reportError,
  };
}
