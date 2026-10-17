import { useCallback, useEffect, useRef, useState } from "react";

const TARGET_RATE = 16000;
const FRAME_SIZE = 640;
const READY_TIMEOUT_MS = 4000;
const FINAL_TIMEOUT_MS = 9000;

export const MIC_DENIED_TEXT = "Не удалось включить микрофон. Разрешите доступ в браузере.";
export const MIC_UNAVAILABLE_TEXT = "Запись с микрофона недоступна в этом браузере.";
export const VOICE_ERROR_TEXT = "Не удалось распознать речь. Попробуйте ещё раз.";

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
}

interface MediaState {
  recorder: MediaRecorder;
  chunks: Blob[];
}

export interface VoiceController {
  recording: boolean;
  busy: boolean;
  partial: string;
  error: string | null;
  start: () => Promise<void>;
  stop: () => Promise<VoiceOutcome>;
  clearError: () => void;
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

export function useVoiceStream(clientId: string): VoiceController {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<StreamState | null>(null);
  const mediaRef = useRef<MediaState | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const mounted = useRef(true);
  const startingRef = useRef(false);
  const stoppingRef = useRef(false);

  const stopMicrophone = useCallback(() => {
    const mic = micRef.current;
    micRef.current = null;
    mic?.getTracks().forEach((track) => track.stop());
  }, []);

  const cleanupStream = useCallback(() => {
    const stream = streamRef.current;
    streamRef.current = null;
    if (!stream) return;
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
      cleanupStream();
      cleanupMedia();
      stopMicrophone();
    };
  }, [cleanupMedia, cleanupStream, stopMicrophone]);

  const startStream = useCallback(async (): Promise<boolean> => {
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

      const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(
        `${scheme}//${window.location.host}/ws/voice?client_id=${encodeURIComponent(clientId)}`,
      );
      socket.binaryType = "arraybuffer";
      stream.socket = socket;
      streamRef.current = stream;

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
          if (mounted.current) setPartial(message.text || "");
        } else if (message.type === "final") {
          stream.resolveFinal({ type: "final", text: message.text || "" });
        } else if (message.type === "error") {
          stream.resolveFinal({ type: "error", text: message.message || VOICE_ERROR_TEXT });
        }
      });
      socket.addEventListener("error", () => {
        if (!readySettled) stream.rejectReady(new Error("voice stream failed to open"));
        stream.resolveFinal({ type: "error", text: VOICE_ERROR_TEXT });
      });
      socket.addEventListener("close", (event) => {
        stream.resolveFinal({ type: "closed" });
        if (!readySettled) {
          stream.rejectReady(new Error("voice stream closed before ready"));
          return;
        }
        if (mounted.current && streamRef.current === stream && event.code !== 1000) {
          setError("Соединение с сервером прервано. Попробуйте ещё раз.");
          cleanupStream();
          stopMicrophone();
          setRecording(false);
        }
      });
      stream.node.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        socket.send(event.data);
      };

      await withTimeout(stream.ready, READY_TIMEOUT_MS);
      return true;
    } catch {
      cleanupStream();
      return false;
    }
  }, [cleanupStream, clientId, stopMicrophone]);

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
      if (typeof navigator.mediaDevices?.getUserMedia !== "function") {
        setError(MIC_UNAVAILABLE_TEXT);
        return;
      }
      try {
        micRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setError(MIC_DENIED_TEXT);
        return;
      }
      if (canStream() && (await startStream())) {
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
  }, [startMedia, startStream, stopMicrophone]);

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

  const stop = useCallback(async (): Promise<VoiceOutcome> => {
    if (stoppingRef.current) return null;
    stoppingRef.current = true;
    setBusy(true);
    try {
      const stream = streamRef.current;
      if (stream) {
        try {
          if (stream.socket?.readyState === WebSocket.OPEN) {
            stream.socket.send(JSON.stringify({ type: "stop" }));
          }
        } catch {
          // The close handler still resolves the stream.
        }
        let outcome: FinalMessage = { type: "timeout" };
        try {
          outcome = await withTimeout(stream.final, FINAL_TIMEOUT_MS);
        } catch {
          outcome = { type: "timeout" };
        }
        cleanupStream();
        stopMicrophone();
        setRecording(false);
        if (outcome.type === "final" && outcome.text) return { kind: "text", text: outcome.text };
        return { kind: "error", message: outcome.text || VOICE_ERROR_TEXT };
      }
      if (mediaRef.current) {
        const blob = await stopMedia();
        stopMicrophone();
        setRecording(false);
        return blob ? { kind: "blob", blob } : { kind: "error", message: VOICE_ERROR_TEXT };
      }
      return null;
    } finally {
      stoppingRef.current = false;
      setBusy(false);
      setPartial("");
    }
  }, [cleanupStream, stopMedia, stopMicrophone]);

  const clearError = useCallback(() => setError(null), []);

  return { recording, busy, partial, error, start, stop, clearError };
}
