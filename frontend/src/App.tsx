import { useCallback, useEffect, useRef, useState } from "react";

import { fetchMeta, reportTelemetry, warmupChat } from "./lib/api";
import { ChatMessage } from "./components/ChatMessage";
import { Composer } from "./components/Composer";
import { LinkPanel } from "./components/LinkPanel";
import { LiveTranscript } from "./components/LiveTranscript";
import { QuickActions } from "./components/QuickActions";
import { ReplyModeSwitch } from "./components/ReplyModeSwitch";
import { TypingIndicator } from "./components/TypingIndicator";
import { VoiceSelect } from "./components/VoiceSelect";
import { useChat } from "./hooks/useChat";
import { useVoiceConversation } from "./hooks/useVoiceConversation";
import { useVoiceStream } from "./hooks/useVoiceStream";
import type { ConversationPhase } from "./lib/conversation";
import { readSpeakReplies, readVoice, writeSpeakReplies, writeVoice } from "./lib/preferences";
import { useSession } from "./lib/session";

const DEFAULT_QUICK_ACTIONS = ["Что у меня сегодня?", "Что на завтра?", "Что на этой неделе?"];
// Зеркало CLOUD_TTS_VOICES из app/ai/tts/cloud_tts.py: виден сразу, /api/meta его заменяет.
const DEFAULT_VOICES = [
  "Mer-Operator",
  "Kaz-Lifelike",
  "Tsb-Freespeech",
  "Gli-Operator",
  "Gli-Freespeech",
  "Bab-Debate",
  "Bab-Energetic",
  "Bab-Freespeech",
  "Tsb-Hesitating",
];

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
  const [voices, setVoices] = useState<string[]>(DEFAULT_VOICES);
  const [voiceName, setVoiceName] = useState(readVoice);
  const session = useSession();
  const chat = useChat();
  const voice = useVoiceStream(chat.clientId);
  const expectedAudioEntryId = useRef<string | null>(null);
  const speechAbortRef = useRef<AbortController | null>(null);
  const conversationPhaseRef = useRef<ConversationPhase>("idle");
  // В синтез уходит ровно тот голос, что показан в списке: устаревший или
  // ещё не выбранный голос заменяется первым из каталога, как его рисует <select>.
  const activeVoice = voices.includes(voiceName) ? voiceName : (voices[0] ?? "");

  /** A newer turn supersedes any speech still being synthesised. */
  const nextSpeechSignal = useCallback(() => {
    speechAbortRef.current?.abort();
    const controller = new AbortController();
    speechAbortRef.current = controller;
    return controller.signal;
  }, []);

  const sendUtterance = useCallback(
    async (text: string, options: { closing: boolean }) => {
      expectedAudioEntryId.current = null;
      const result = await chat.sendText(text, {
        speak: speakReplies,
        voice: activeVoice,
        closing: options.closing,
        signal: nextSpeechSignal(),
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
    [chat.sendText, speakReplies, activeVoice, nextSpeechSignal],
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
        voice: activeVoice,
        // Переключение на «Текстом» отменяет и синтез набранного ответа.
        signal: nextSpeechSignal(),
        onSpeechError: (message) => {
          reportTelemetry("speech_failed", conversationPhaseRef.current, message);
        },
      });
    },
    [chat.sendText, speakReplies, activeVoice, nextSpeechSignal],
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
          const catalogue = meta.voices;
          setVoices(catalogue);
          // Сохранённый голос, которого больше нет на сервере, синтез не примет.
          setVoiceName((current) => {
            if (catalogue.includes(current)) return current;
            if (meta.voice && catalogue.includes(meta.voice)) return meta.voice;
            return catalogue[0];
          });
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
      await chat.sendText(outcome.text, {
        speak: speakReplies,
        voice: activeVoice,
        signal: nextSpeechSignal(),
      });
    } else if (outcome.kind === "blob") {
      await chat.sendVoice(outcome.blob, { voice: activeVoice });
    } else {
      chat.reportError(outcome.message);
    }
  };
  // Ответ ещё не пришёл: в чате «Отвечаю», нижняя строка статуса молчит, чтобы не дублировать.
  const awaitingReply = chat.pending && chat.entries[chat.entries.length - 1]?.role === "user";
  const status = voice.busy
    ? "Распознаю…"
    : chat.synthesizingEntryId
      ? "Озвучиваю ответ…"
      : conversation.active
        ? conversation.status
        : awaitingReply
          ? ""
          : chat.status || conversation.hint;
  const composerDisabled = chat.pending || voice.busy;

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col border-x border-line/60">
      <header className="flex flex-col gap-4 border-b border-line/70 px-4 py-4 sm:px-6">
        {/* Мобилка: название + шестерёнка в строку, переключатели ниже. Планшет/ПК: всё в одну строку.
            Все элементы высотой 36px и прижаты к верху: подпись под переключателем свисает вниз,
            не сдвигая соседей. */}
        <div className="flex flex-wrap items-start gap-x-3 gap-y-3">
          <div className="order-1 flex h-9 min-w-0 flex-1 items-center">
            <div className="min-w-0">
              <h1 className="truncate text-base font-semibold leading-tight">Ассистент задач и встреч</h1>
              
            </div>
          </div>
          <div className="order-2 sm:order-3">
            <LinkPanel />
          </div>
          <div className="order-3 flex w-full min-w-0 items-start gap-2 sm:order-2 sm:w-auto">
            <ReplyModeSwitch
              speak={speakReplies}
              onChange={(next) => {
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
            />
            <VoiceSelect
              voices={voices}
              value={activeVoice}
              disabled={!speakReplies}
              onChange={(next) => {
                setVoiceName(next);
                writeVoice(next);
              }}
            />
          </div>
        </div>
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
        {awaitingReply ? <TypingIndicator /> : null}
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
          {status || (awaitingReply ? null : "Нажмите «Голосом» и говорите — текст появляется на лету.")}
        </p>
      </footer>
    </div>
  );
}
