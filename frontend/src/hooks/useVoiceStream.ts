import { readSessionToken } from "../lib/api";
import { useCallback, useEffect, useRef, useState } from "react";

import type { VoiceTurnOutcome } from "../lib/conversation";
import { pcm16Energy } from "../lib/vad";

const TARGET_RATE = 16000;
const FRAME_SIZE = 640;
const READY_TIMEOUT_MS = 4000;
const FINAL_TIMEOUT_MS = 9000;

export const MIC_DENIED_TEXT = "Не удалось включить микрофон. Разрешите доступ в браузере.";
export const MIC_UNAVAILABLE_TEXT = "Запись с микрофона недоступна в этом браузере.";
export const VOICE_ERROR_TEXT = "Не удалось распознать речь. Попробуйте ещё раз.";
export const STREAM_START_TEXT = "Не удалось начать запись. Попробуйте ещё раз.";

export type VoiceOutcome =
  | { kind: "text"; text: string }
  | { kind: "blob"; blob: Blob }
  | { kind: "error"; message: string }
  | null;

interface FinalMessage {
  type: "final" | "error" | "closed" | "timeout";
  text?: string;
}

interface StreamState {
  context: AudioContext | null;
  source: MediaStreamAudioSourceNode | null;
  node: AudioWorkletNode | null;
  sink: GainNode | null;
  socket: WebSocket | null;
  final: Promise<FinalMessage>;
  resolveFinal: (message: FinalMessage) => void;
  rejectReady: (error: Error) => void;
  ready: Promise<void>;
  intentional: boolean;
  /** A muted turn keeps capturing energy but sends no frames to the server. */
  muted: boolean;
}

interface MediaState {
  recorder: MediaRecorder;
  chunks: Blob[];
}

export interface BeginTurnOptions {
  /** Capture frames but do not forward them until `unmute()` is called. */
  muted?: boolean;
}

export interface VoiceController {
  recording: boolean;
  busy: boolean;
  partial: string;
  error: string | null;
  /** True when this browser can stream PCM frames and show server partials. */
  streaming: boolean;
  /** One-shot path kept for the regular "Голосом" button and the blob fallback. */
  start: () => Promise<void>;
  stop: () => Promise<VoiceOutcome>;
  clearError: () => void;
  /** Conversation-mode primitives: one microphone, one streaming turn at a time. */
  openMicrophone: () => Promise<boolean>;
  beginTurn: (options?: BeginTurnOptions) => Promise<boolean>;
  commitTurn: () => Promise<VoiceTurnOutcome>;
  releaseMicrophone: () => void;
  /** Stops forwarding frames on the current turn without closing anything. */
  mute: () => void;
  /** Resumes forwarding frames on the current turn. */
  unmute: () => void;
  subscribeEnergy: (handler: (energy: number) => void) => () => void;
}

/** Echo cancellation keeps the assistant's own voice out of the barge-in check. */
const PREFERRED_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

const FALLBACK_AUDIO_CONSTRAINTS: MediaStreamConstraints = { audio: true };

async function requestMicrophone(): Promise<MediaStream> {
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: PREFERRED_AUDIO_CONSTRAINTS,
    });
  } catch {
    // Constraints are not supported everywhere; a plain audio stream still works.
    return navigator.mediaDevices.getUserMedia(FALLBACK_AUDIO_CONSTRAINTS);
  }
}


function withTimeout<T>(promise: Promise<T>, milliseconds: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => {
      window.setTimeout(() => reject(new Error("timeout")), milliseconds);
    }),
  ]);
}

function canStream(): boolean {
  return (
    "WebSocket" in window &&
    "AudioWorkletNode" in window &&
    typeof window.AudioContext === "function" &&
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    window.location.protocol !== "file:"
  );
}

function disposeStreamResources(stream: StreamState): void {
  try {
    if (stream.socket && stream.socket.readyState <= WebSocket.OPEN) stream.socket.close();
  } catch {
    // Socket is already gone.
  }
  if (stream.node) stream.node.port.onmessage = null;
  [stream.source, stream.node, stream.sink].forEach((node) => {
    try {
      node?.disconnect();
    } catch {
      // Node was never connected.
    }
  });
  if (stream.context) void stream.context.close().catch(() => {});
}

export function useVoiceStream(): VoiceController {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [streaming] = useState(canStream);
  const streamRef = useRef<StreamState | null>(null);
  const mediaRef = useRef<MediaState | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const energyHandlers = useRef(new Set<(energy: number) => void>());
  const mounted = useRef(true);
  const startingRef = useRef(false);
  const stoppingRef = useRef(false);
  const openingRef = useRef<Promise<boolean> | null>(null);

  const stopMicrophone = useCallback(() => {
    const mic = micRef.current;
    micRef.current = null;
    mic?.getTracks().forEach((track) => track.stop());
  }, []);

  const cleanupStream = useCallback(() => {
    const stream = streamRef.current;
    streamRef.current = null;
    if (stream) disposeStreamResources(stream);
  }, []);

  const cleanupMedia = useCallback(() => {
    const media = mediaRef.current;
    mediaRef.current = null;
    if (media && media.recorder.state !== "inactive") {
      try {
        media.recorder.stop();
      } catch {
        // Recorder was already stopped.
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      openingRef.current = null;
      cleanupStream();
      cleanupMedia();
      stopMicrophone();
    };
  }, [cleanupMedia, cleanupStream, stopMicrophone]);

  const subscribeEnergy = useCallback((handler: (energy: number) => void) => {
    energyHandlers.current.add(handler);
    return () => {
      energyHandlers.current.delete(handler);
    };
  }, []);

  const acquireMicrophone = useCallback(async (): Promise<boolean> => {
    setError(null);
    if (typeof navigator.mediaDevices?.getUserMedia !== "function") {
      setError(MIC_UNAVAILABLE_TEXT);
      return false;
    }
    try {
      const mic = await requestMicrophone();
      if (!mounted.current) {
        mic.getTracks().forEach((track) => track.stop());
        return false;
      }
      micRef.current = mic;
      return true;
    } catch {
      if (mounted.current) setError(MIC_DENIED_TEXT);
      return false;
    }
  }, []);

  const openMicrophone = useCallback((): Promise<boolean> => {
    if (micRef.current) return Promise.resolve(true);
    if (openingRef.current) return openingRef.current;
    const pending = acquireMicrophone().finally(() => {
      openingRef.current = null;
    });
    openingRef.current = pending;
    return pending;
  }, [acquireMicrophone]);

  const startStream = useCallback(async (muted: boolean): Promise<boolean> => {
    const mic = micRef.current;
    if (!mic) return false;

    const stream: StreamState = {
      context: null,
      source: null,
      node: null,
      sink: null,
      socket: null,
      final: Promise.resolve({ type: "closed" }),
      resolveFinal: () => {},
      rejectReady: () => {},
      ready: Promise.resolve(),
      intentional: false,
      muted,
    };

    try {
      stream.context = new AudioContext({ sampleRate: TARGET_RATE });
      await stream.context.audioWorklet.addModule("/pcm-worklet.js");
      if (stream.context.state === "suspended") await stream.context.resume();
      stream.source = stream.context.createMediaStreamSource(mic);
      stream.node = new AudioWorkletNode(stream.context, "pcm-capture", {
        processorOptions: { targetRate: TARGET_RATE, frameSize: FRAME_SIZE },
      });
      stream.sink = stream.context.createGain();
      stream.sink.gain.value = 0;
      stream.source.connect(stream.node);
      stream.node.connect(stream.sink);
      stream.sink.connect(stream.context.destination);

      let readySettled = false;
      let resolveReady = () => {};
      stream.ready = new Promise<void>((resolve, reject) => {
        resolveReady = () => {
          readySettled = true;
          resolve();
        };
        stream.rejectReady = reject;
      });
      stream.final = new Promise<FinalMessage>((resolve) => {
        stream.resolveFinal = resolve;
      });

      const failLiveStream = () => {
        if (!mounted.current || streamRef.current !== stream || stream.intentional) return;
        setError("Соединение с сервером прервано. Попробуйте ещё раз.");
        cleanupStream();
        stopMicrophone();
        setPartial("");
        setRecording(false);
      };

      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(`${scheme}//${window.location.host}/ws/voice`);
      socket.binaryType = "arraybuffer";
      socket.addEventListener("open", () => {
        const token = readSessionToken();
        if (!token) {
          socket.close(1008, "authentication required");
          return;
        }
        socket.send(JSON.stringify({ type: "auth", token }));
      });
      stream.socket = socket;
      streamRef.current = stream;
      if (!mounted.current) {
        streamRef.current = null;
        disposeStreamResources(stream);
        return false;
      }

      socket.addEventListener("message", (event) => {
        let message: { type?: string; text?: string; message?: string } | null = null;
        try {
          message = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (!message) return;
        if (message.type === "ready") {
          resolveReady();
        } else if (message.type === "partial") {
          if (mounted.current && !stream.intentional) setPartial(message.text || "");
        } else if (message.type === "final") {
          stream.resolveFinal({ type: "final", text: message.text || "" });
        } else if (message.type === "error") {
          stream.resolveFinal({ type: "error", text: message.message || VOICE_ERROR_TEXT });
        }
      });
      socket.addEventListener("error", () => {
        if (!readySettled) stream.rejectReady(new Error("voice stream failed to open"));
        stream.resolveFinal({ type: "error", text: VOICE_ERROR_TEXT });
        if (readySettled) failLiveStream();
      });
      socket.addEventListener("close", () => {
        stream.resolveFinal({ type: "closed" });
        if (!readySettled) {
          stream.rejectReady(new Error("voice stream closed before ready"));
          return;
        }
        failLiveStream();
      });
      stream.node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        const energy = pcm16Energy(event.data);
        energyHandlers.current.forEach((handler) => handler(energy));
        // A muted turn still measures energy (barge-in) but stays silent
        // towards the recognizer: no partials, no auto-commit.
        if (stream.muted) return;
        if (socket.readyState !== WebSocket.OPEN) return;
        socket.send(event.data);
      };

      await withTimeout(stream.ready, READY_TIMEOUT_MS);
      if (!mounted.current) {
        if (streamRef.current === stream) streamRef.current = null;
        disposeStreamResources(stream);
        return false;
      }
      return true;
    } catch {
      if (streamRef.current === stream) streamRef.current = null;
      disposeStreamResources(stream);
      return false;
    }
  }, [cleanupStream, stopMicrophone]);

  const startMedia = useCallback((): boolean => {
    const mic = micRef.current;
    if (!mic || typeof window.MediaRecorder === "undefined") return false;
    const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
    const mimeType = candidates.find((type) => window.MediaRecorder.isTypeSupported(type));
    const recorder = mimeType ? new MediaRecorder(mic, { mimeType }) : new MediaRecorder(mic);
    const chunks: Blob[] = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    });
    mediaRef.current = { recorder, chunks };
    recorder.start();
    return true;
  }, []);

  const start = useCallback(async () => {
    if (startingRef.current || micRef.current) return;
    startingRef.current = true;
    try {
      setError(null);
      setPartial("");
      if (!(await openMicrophone())) return;
      if (canStream() && (await startStream(false))) {
        setRecording(true);
        return;
      }
      if (!startMedia()) {
        setError(MIC_UNAVAILABLE_TEXT);
        stopMicrophone();
        return;
      }
      setRecording(true);
    } finally {
      startingRef.current = false;
    }
  }, [openMicrophone, startMedia, startStream, stopMicrophone]);

  const stopMedia = useCallback(async (): Promise<Blob | null> => {
    const media = mediaRef.current;
    if (!media) return null;
    const blob = await new Promise<Blob>((resolve) => {
      const finish = () => {
        const mimeType = media.chunks[0]?.type || "audio/webm";
        resolve(new Blob(media.chunks, { type: mimeType }));
      };
      if (media.recorder.state === "inactive") finish();
      else {
        media.recorder.addEventListener("stop", finish, { once: true });
        media.recorder.stop();
      }
    });
    mediaRef.current = null;
    return blob.size > 0 ? blob : null;
  }, []);

  const finishStreamTurn = useCallback(async (): Promise<VoiceTurnOutcome> => {
    const stream = streamRef.current;
    if (!stream) return { kind: "empty" };
    stream.intentional = true;
    try {
      if (stream.socket?.readyState === WebSocket.OPEN) {
        stream.socket.send(JSON.stringify({ type: "stop" }));
      }
    } catch {
      // The close handler still resolves the stream.
    }
    // Stop feeding frames to the server while it finalizes the transcript.
    if (stream.node) stream.node.port.onmessage = null;
    try {
      stream.source?.disconnect();
    } catch {
      // The source was already disconnected.
    }

    let outcome: FinalMessage = { type: "timeout" };
    try {
      outcome = await withTimeout(stream.final, FINAL_TIMEOUT_MS);
    } catch {
      outcome = { type: "timeout" };
    }
    cleanupStream();
    if (mounted.current) setPartial("");

    if (outcome.type === "final") {
      const text = (outcome.text ?? "").trim();
      return text ? { kind: "text", text } : { kind: "empty" };
    }
    if (outcome.type === "error") {
      return { kind: "error", message: outcome.text || VOICE_ERROR_TEXT };
    }
    return { kind: "error", message: outcome.text || VOICE_ERROR_TEXT };
  }, [cleanupStream]);

  const commitTurn = useCallback(async (): Promise<VoiceTurnOutcome> => {
    if (stoppingRef.current) return { kind: "empty" };
    stoppingRef.current = true;
    setBusy(true);
    try {
      return await finishStreamTurn();
    } finally {
      stoppingRef.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [finishStreamTurn]);

  const stop = useCallback(async (): Promise<VoiceOutcome> => {
    if (stoppingRef.current) return null;
    const stream = streamRef.current;
    if (stream) {
      const outcome = await commitTurn();
      stopMicrophone();
      if (mounted.current) setRecording(false);
      if (outcome.kind === "text") return { kind: "text", text: outcome.text };
      return {
        kind: "error",
        message: outcome.kind === "error" ? outcome.message : VOICE_ERROR_TEXT,
      };
    }
    if (mediaRef.current) {
      stoppingRef.current = true;
      setBusy(true);
      try {
        const blob = await stopMedia();
        stopMicrophone();
        if (mounted.current) setRecording(false);
        return blob ? { kind: "blob", blob } : { kind: "error", message: VOICE_ERROR_TEXT };
      } finally {
        stoppingRef.current = false;
        if (mounted.current) setBusy(false);
      }
    }
    return null;
  }, [commitTurn, stopMedia, stopMicrophone]);

  const mute = useCallback(() => {
    if (streamRef.current) streamRef.current.muted = true;
  }, []);

  const unmute = useCallback(() => {
    if (streamRef.current) streamRef.current.muted = false;
  }, []);

  const beginTurn = useCallback(
    async (options?: BeginTurnOptions): Promise<boolean> => {
      if (!micRef.current) return false;
      if (!canStream()) {
        setError(MIC_UNAVAILABLE_TEXT);
        return false;
      }
      if (streamRef.current) {
        // The turn is already streaming: muting is only a forwarding flag.
        if (options?.muted) mute();
        else unmute();
        return true;
      }
      setError(null);
      setPartial("");
      const started = await startStream(options?.muted ?? false);
      if (!started) {
        // A manual release stops the microphone; do not surface that as an error.
        if (mounted.current && micRef.current) setError((current) => current ?? STREAM_START_TEXT);
        return false;
      }
      if (!mounted.current || !streamRef.current) {
        cleanupStream();
        return false;
      }
      setRecording(true);
      return true;
    },
    [cleanupStream, mute, startStream, unmute],
  );

  const releaseMicrophone = useCallback(() => {
    openingRef.current = null;
    cleanupStream();
    cleanupMedia();
    stopMicrophone();
    if (mounted.current) {
      setRecording(false);
      setBusy(false);
      setPartial("");
    }
  }, [cleanupMedia, cleanupStream, stopMicrophone]);

  const clearError = useCallback(() => setError(null), []);

  return {
    recording,
    busy,
    partial,
    error,
    streaming,
    start,
    stop,
    clearError,
    openMicrophone,
    beginTurn,
    commitTurn,
    releaseMicrophone,
    mute,
    unmute,
    subscribeEnergy,
  };
}
