import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { completeEvent, errorMessage, postChat, postVoice, readClientId } from "../lib/api";
import type { ChatEntry } from "../types";

export interface ChatController {
  clientId: string;
  entries: ChatEntry[];
  pending: boolean;
  status: string;
  sendText: (text: string, options?: { speak?: boolean }) => Promise<void>;
  sendVoice: (blob: Blob) => Promise<void>;
  complete: (eventId: number) => Promise<void>;
  reportError: (message: string) => void;
}

export function useChat(): ChatController {
  const clientId = useMemo(readClientId, []);
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  const counter = useRef(0);

  const nextId = useCallback(() => {
    counter.current += 1;
    return `m${counter.current}`;
  }, []);

  const append = useCallback((entry: ChatEntry) => {
    setEntries((current) => [...current, entry]);
  }, []);

  const sendText = useCallback(
    async (raw: string, options?: { speak?: boolean }) => {
      const text = raw.trim();
      if (!text || pending) return;
      append({ id: nextId(), role: "user", text });
      setPending(true);
      setStatus("Обрабатываю…");
      try {
        const reply = await postChat(text, clientId, options?.speak ?? false);
        append({ id: nextId(), role: "assistant", reply });
      } catch (error) {
        append({ id: nextId(), role: "error", text: errorMessage(error) });
      } finally {
        setPending(false);
        setStatus("");
      }
    },
    [append, clientId, nextId, pending],
  );

  const sendVoice = useCallback(
    async (blob: Blob) => {
      if (pending) return;
      append({ id: nextId(), role: "user", text: "Голосовое сообщение" });
      setPending(true);
      setStatus("Распознаю…");
      try {
        const reply = await postVoice(blob, clientId);
        append({ id: nextId(), role: "assistant", reply });
      } catch (error) {
        append({ id: nextId(), role: "error", text: errorMessage(error) });
      } finally {
        setPending(false);
        setStatus("");
      }
    },
    [append, clientId, nextId, pending],
  );

  const complete = useCallback(
    async (eventId: number) => {
      const updated = await completeEvent(eventId, clientId);
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
    [clientId],
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

  return { clientId, entries, pending, status, sendText, sendVoice, complete, reportError };
}
