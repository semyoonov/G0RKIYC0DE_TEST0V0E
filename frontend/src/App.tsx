import { useCallback, useEffect, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";

import { fetchMeta, reportTelemetry, warmupChat } from "./lib/api";
import { ChatMessage } from "./components/ChatMessage";
import { Composer } from "./components/Composer";
import { LinkPanel } from "./components/LinkPanel";
import { LiveTranscript } from "./components/LiveTranscript";
import { QuickActions } from "./components/QuickActions";
import { VoiceSelect } from "./components/VoiceSelect";
import { useChat } from "./hooks/useChat";
import { useVoiceConversation } from "./hooks/useVoiceConversation";
import { useVoiceStream } from "./hooks/useVoiceStream";
import type { ConversationPhase } from "./lib/conversation";
import { readSpeakReplies, readVoice, writeSpeakReplies, writeVoice } from "./lib/preferences";
import { useSession } from "./lib/session";

const DEFAULT_QUICK_ACTIONS = ["Что у меня сегодня?", "Что на завтра?", "Что на этой неделе?"];

function initialTimezone(): string {
  const tag = document.querySelector<HTMLMetaElement>('meta[name="assistant-timezone"]');
  const value = tag?.content?.trim() ?? "";
  if (value && !value.startsWith("__")) return value;
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Moscow";
}

export default function App() {
  const [timezone, setTimezone] = useState(initialTimezone);
  const [quickActions, setQuickActions] = useState<string[]>(DEFAULT_QUICK_ACTIONS);
  const [speakReplies, setSpeakReplies] = useState(readSpeakReplies);
  const [voices, setVoices] = useState<string[]>([]);
  const [voiceName, setVoiceName] = useState(readVoice);
  const session = useSession();
  const chat = useChat();
  const voice = useVoiceStream(chat.clientId);
  const expectedAudioEntryId = useRef<string | null>(null);
  const speechAbortRef = useRef<AbortController | null>(null);
  const conversationPhaseRef = useRef<ConversationPhase>("idle");

  const sendUtterance = useCallback(
    async (text: string, options: { closing: boolean }) => {
      expectedAudioEntryId.current = null;
      // A newer turn supersedes any speech still being synthesised.
      speechAbortRef.current?.abort();
      const controller = new AbortController();
      speechAbortRef.current = controller;
      const result = await chat.sendText(text, {
        speak: speakReplies,
        voice: voiceName,
        closing: options.closing,
        signal: controller.signal,
        onReplyEntry: (entryId) => {
          expectedAudioEntryId.current = entryId;
        },
        onSpeechError: (message) => {
          reportTelemetry("speech_failed", conversationPhaseRef.current, message);
        },
      });
      return {
        ok: result.error === null,
        hasAudio: result.hasAudio,
      };
    },
    [chat.sendText, speakReplies, voiceName],
  );

  const conversation = useVoiceConversation({
    voice,
    sendUtterance,
    reportError: chat.reportError,
    warmup: () => {
      void warmupChat();
    },
    telemetry: reportTelemetry,
  });
  conversationPhaseRef.current = conversation.phase;

  // Leaving the dialogue (or unmounting) cancels speech that is still loading.
  useEffect(() => {
    if (conversation.active) return;
    speechAbortRef.current?.abort();
    speechAbortRef.current = null;
  }, [conversation.active]);

  useEffect(() => {
    return () => {
      speechAbortRef.current?.abort();
      speechAbortRef.current = null;
    };
  }, []);

  const sendTyped = useCallback(
    (text: string) => {
      void chat.sendText(text, {
        speak: speakReplies,
        voice: voiceName,
        onSpeechError: (message) => {
          reportTelemetry("speech_failed", conversationPhaseRef.current, message);
        },
      });
    },
    [chat.sendText, speakReplies, voiceName],
  );
  const handleReplyAudioEnd = useCallback(
    (entryId: string) => {
      if (expectedAudioEntryId.current !== entryId) return;
      conversation.notifyPlaybackFinished();
    },
    [conversation.notifyPlaybackFinished],
  );
  const messagesRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMeta()
      .then((meta) => {
        if (cancelled) return;
        if (meta.timezone) setTimezone(meta.timezone);
        if (meta.quick_actions.length > 0) setQuickActions(meta.quick_actions);
        if (meta.voices && meta.voices.length > 0) {
          setVoices(meta.voices);
          setVoiceName((current) => current || meta.voice || meta.voices![0]);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (session.status === "ready") void warmupChat();
  }, [session.status]);

  useEffect(() => {
    const element = messagesRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [chat.entries, voice.partial, chat.pending, conversation.phase]);

  const toggleRecording = async () => {
    if (voice.streaming) {
      await conversation.toggle();
      return;
    }
    if (!voice.recording) {
      await voice.start();
      return;
    }
    const outcome = await voice.stop();
    if (!outcome) return;
    if (outcome.kind === "text") {
      await chat.sendText(outcome.text, { speak: speakReplies, voice: voiceName });
    } else if (outcome.kind === "blob") {
      await chat.sendVoice(outcome.blob);
    } else {
      chat.reportError(outcome.message);
    }
  };
  const status = voice.busy
    ? "Распознаю…"
    : chat.synthesizingEntryId
      ? "Озвучиваю ответ…"
      : conversation.active
        ? conversation.status
        : chat.status || conversation.hint;
  const composerDisabled = chat.pending || voice.busy;

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col border-x border-line/60">
      <header className="flex flex-col gap-4 border-b border-line/70 px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-sm font-semibold text-accent">
              А
            </span>
            <div>
              <h1 className="text-base font-semibold leading-tight">Ассистент задач и встреч</h1>
              <p className="text-xs text-ink-muted">Голосом или текстом</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            role="switch"
            aria-checked={speakReplies}
            aria-label="Озвучивать ответы"
            onClick={() => {
              const next = !speakReplies;
              setSpeakReplies(next);
              writeSpeakReplies(next);
              if (!next) {
                speechAbortRef.current?.abort();
                speechAbortRef.current = null;
                document.querySelectorAll("audio").forEach((node) => node.pause());
                expectedAudioEntryId.current = null;
                conversation.notifyPlaybackFinished();
              }
            }}
            className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs transition ${
              speakReplies
                ? "border-accent/50 bg-accent-soft text-accent"
                : "border-line text-ink-muted hover:text-ink"
            }`}
          >
            {speakReplies ? <Volume2 className="size-3.5" /> : <VolumeX className="size-3.5" />}
            Озвучивать ответы
            <span className="text-[11px] opacity-70">{speakReplies ? "вкл" : "выкл"}</span>
          </button>
          <VoiceSelect
            voices={voices}
            value={voiceName}
            disabled={!speakReplies}
            onChange={(next) => {
              setVoiceName(next);
              writeVoice(next);
            }}
          />
          </div>
        </div>
        <LinkPanel />
        <QuickActions
          actions={quickActions}
          disabled={composerDisabled || voice.recording || conversation.active}
          onSelect={sendTyped}
        />
      </header>

      <main
        ref={messagesRef}
        className="flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6"
        aria-live="polite"
      >
        <div className="max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-panel px-4 py-3 text-sm leading-relaxed text-ink-muted">
          Здравствуйте! Напишите или скажите, что запланировать: задачу, встречу или напоминание.
        </div>
        {chat.entries.map((entry) => (
          <ChatMessage
            key={entry.id}
            entry={entry}
            timezone={timezone}
            autoPlayAudio={speakReplies}
            synthesizing={chat.synthesizingEntryId === entry.id}
            onComplete={chat.complete}
            onReplyAudioEnd={handleReplyAudioEnd}
          />
        ))}
        {voice.error ? (
          <div className="max-w-[92%] rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {voice.error}
          </div>
        ) : null}
      </main>

      <footer className="border-t border-line/60">
        <LiveTranscript text={voice.partial} />
        <Composer
          disabled={composerDisabled}
          recording={voice.recording}
          busy={voice.busy}
          conversationActive={conversation.active}
          conversationPhase={conversation.phase}
          onSend={sendTyped}
          onToggleRecording={() => void toggleRecording()}
        />
        <p className="min-h-5 px-4 pb-2 text-xs text-ink-dim sm:px-6" role="status">
          {status || "Нажмите «Голосом» и говорите — текст появляется на лету."}
        </p>
      </footer>
    </div>
  );
}
