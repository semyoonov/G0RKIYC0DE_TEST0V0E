import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  completeEvent,
  errorMessage,
  postChat,
  postSpeech,
  postVoice,
  readClientId,
} from "../lib/api";
import type { ChatEntry, ChatReply } from "../types";

export interface ChatTurnResult {
  reply: ChatReply | null;
  error: string | null;
  /** True when reply audio was returned inline or attached after the text. */
  hasAudio: boolean;
}

export interface SendTextOptions {
  /** Fetch speech in a separate request and attach it to the rendered reply. */
  speak?: boolean;
  closing?: boolean;
  voice?: string;
  /** Cancels the speech request; the text reply is kept regardless. */
  signal?: AbortSignal;
  /** Reports the assistant entry id as soon as the reply is appended. */
  onReplyEntry?: (entryId: string) => void;
  /** Speech synthesis failed, but the text reply is already rendered. */
  onSpeechError?: (message: string) => void;
}

export interface ChatController {
  clientId: string;
  entries: ChatEntry[];
  pending: boolean;
  status: string;
  /** Assistant entry whose speech is being synthesised right now. */
  synthesizingEntryId: string | null;
  sendText: (text: string, options?: SendTextOptions) => Promise<ChatTurnResult>;
  sendVoice: (blob: Blob) => Promise<void>;
  /** Attaches speech to an assistant entry that is already on screen. */
  attachAudio: (entryId: string, audio: string, mime: string | null) => void;
  complete: (eventId: number) => Promise<void>;
  reportError: (message: string) => void;
}

function isAbort(error: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true;
  return (error as { name?: string } | null)?.name === "AbortError";
}

export function useChat(): ChatController {
  const clientId = useMemo(readClientId, []);
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
        // The answer is requested without speech so its text renders at once.
        const reply = await postChat(text, clientId, {
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
          // Speak the assistant's answer, not the user's utterance.
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
    [append, attachAudio, clientId, nextId, pending],
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

  return {
    clientId,
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
