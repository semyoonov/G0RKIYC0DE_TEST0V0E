import { useEffect, useRef, useState } from "react";
import { Volume2, VolumeX } from "lucide-react";

import { fetchMeta } from "./lib/api";
import { ChatMessage } from "./components/ChatMessage";
import { Composer } from "./components/Composer";
import { LinkPanel } from "./components/LinkPanel";
import { LiveTranscript } from "./components/LiveTranscript";
import { QuickActions } from "./components/QuickActions";
import { useChat } from "./hooks/useChat";
import { useVoiceStream } from "./hooks/useVoiceStream";
import { readSpeakReplies, writeSpeakReplies } from "./lib/preferences";

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
  const chat = useChat();
  const voice = useVoiceStream(chat.clientId);
  const messagesRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMeta()
      .then((meta) => {
        if (cancelled) return;
        if (meta.timezone) setTimezone(meta.timezone);
        if (meta.quick_actions.length > 0) setQuickActions(meta.quick_actions);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const element = messagesRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [chat.entries, voice.partial, chat.pending]);

  const toggleRecording = async () => {
    if (!voice.recording) {
      await voice.start();
      return;
    }
    const outcome = await voice.stop();
    if (!outcome) return;
    if (outcome.kind === "text") {
      await chat.sendText(outcome.text, { speak: speakReplies });
    } else if (outcome.kind === "blob") {
      await chat.sendVoice(outcome.blob);
    } else {
      chat.reportError(outcome.message);
    }
  };

  const status = voice.busy ? "Распознаю…" : chat.status;
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
          <button
            type="button"
            role="switch"
            aria-checked={speakReplies}
            aria-label="Озвучивать ответы"
            onClick={() => {
              const next = !speakReplies;
              setSpeakReplies(next);
              writeSpeakReplies(next);
              if (!next) document.querySelectorAll("audio").forEach((node) => node.pause());
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
        </div>
        <LinkPanel />
        <QuickActions
          actions={quickActions}
          disabled={composerDisabled || voice.recording}
          onSelect={(action) => void chat.sendText(action, { speak: speakReplies })}
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
            onComplete={chat.complete}
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
          onSend={(text) => void chat.sendText(text, { speak: speakReplies })}
          onToggleRecording={() => void toggleRecording()}
        />
        <p className="min-h-5 px-4 pb-2 text-xs text-ink-dim sm:px-6" role="status">
          {status}
        </p>
      </footer>
    </div>
  );
}
