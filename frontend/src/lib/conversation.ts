import { isFarewellUtterance } from "./farewell";

export type ConversationPhase = "idle" | "listening" | "thinking" | "speaking" | "ended";

export type VoiceTurnOutcome =
  | { kind: "text"; text: string }
  | { kind: "empty" }
  | { kind: "error"; message: string };

/** Microphone and per-turn websocket operations used by the loop. */
export interface VoiceTurnPort {
  /** Acquires the microphone once for the whole conversation. */
  open(): Promise<boolean>;
  /**
   * Starts a streaming turn on the already open microphone. A muted turn keeps
   * capturing frames locally but does not send them to the recognizer.
   */
  beginTurn(options?: { muted?: boolean }): Promise<boolean>;
  /** Stops the turn and resolves with its final transcript. */
  commitTurn(): Promise<VoiceTurnOutcome>;
  /** Releases the microphone when the mode ends. */
  release(): void;
  /** Resumes forwarding frames on the turn that is already open. */
  unmute(): void;
}

export interface ConversationSendResult {
  ok: boolean;
  hasAudio: boolean;
}

export type ConversationSend = (
  text: string,
  options: { closing: boolean },
) => Promise<ConversationSendResult>;

export interface ConversationLoopOptions {
  voice: VoiceTurnPort;
  sendUtterance: ConversationSend;
  /** Defaults to the shared farewell detector. */
  isFarewell?: (text: string) => boolean;
  /** Reports whether the current turn contains actual speech. */
  hasSpeech?: () => boolean;
  onPhase?: (phase: ConversationPhase) => void;
  onActiveChange?: (active: boolean) => void;
  onError?: (message: string) => void;
  onFarewell?: () => void;
  /** Best-effort diagnostics; receives the loop's phase at the time of the event. */
  onTelemetry?: (event: string, phase: ConversationPhase, detail: string) => void;
  /** Quiet pause before a fallback listening turn is reopened. */
  guardMs?: number;
  /** Safety net when a playback callback never arrives. */
  playbackTimeoutMs?: number;
  delay?: (milliseconds: number) => Promise<void>;
}

interface PlaybackGate {
  readonly promise: Promise<void>;
  settle: () => void;
}

function createPlaybackGate(): PlaybackGate {
  let settleFn: (() => void) | null = null;
  const promise = new Promise<void>((resolve) => {
    settleFn = resolve;
  });
  return {
    promise,
    settle: () => {
      const current = settleFn;
      settleFn = null;
      current?.();
    },
  };
}

function defaultDelay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, milliseconds);
  });
}

type TurnState = "idle" | "opening" | "listening" | "committing" | "sending" | "muted";

/**
 * Hands-free dialogue that keeps one microphone and one streaming turn alive:
 *
 * listen -> commit -> send -> think (next turn opens muted) -> speak (muted,
 * barge-in armed) -> unmute -> listen again in the same turn
 *
 * The turn that is opened in muted mode while the answer is generated becomes
 * the next listening turn: after playback it is merely unmuted, so neither the
 * microphone nor the websocket is reopened. A short farewell is sent with
 * `closing: true` and the loop ends after its reply. An empty turn starts
 * listening again instead of surfacing an error, and a failed request keeps
 * the microphone and resumes listening. The loop owns no React state.
 */
export class ConversationLoop {
  private readonly options: ConversationLoopOptions;
  private readonly guardMs: number;
  private readonly isFarewell: (text: string) => boolean;

  private active = false;
  private phase: ConversationPhase = "idle";
  private turn: TurnState = "idle";
  private generation = 0;
  private stopRequested = false;
  private gate: PlaybackGate | null = null;

  constructor(options: ConversationLoopOptions) {
    this.options = options;
    this.guardMs = options.guardMs ?? 400;
    this.isFarewell = options.isFarewell ?? isFarewellUtterance;
  }

  get isActive(): boolean {
    return this.active;
  }

  get currentPhase(): ConversationPhase {
    return this.phase;
  }

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.stopRequested = false;
    this.gate?.settle();
    this.gate = null;
    const generation = (this.generation += 1);
    this.setActive(true);
    this.setPhase("listening");

    const opened = await this.options.voice.open();
    if (generation !== this.generation) return;
    if (!opened) {
      this.finish(generation, "idle");
      return;
    }
    if (!this.active || this.stopRequested) {
      this.options.voice.release();
      return;
    }
    await this.listen(generation);
  }

  /** Auto-commit: only valid while a listening turn is in progress. */
  async commit(): Promise<void> {
    if (!this.active || this.stopRequested || this.turn !== "listening") return;
    await this.commitTurn(this.generation, false);
  }

  /** Manual stop: commit what is streaming, then leave the mode. */
  async stop(): Promise<void> {
    if (!this.active) return;
    const generation = this.generation;
    const wasListening = this.turn === "listening";
    this.active = false;
    this.stopRequested = true;
    this.setActive(false);

    if (wasListening) {
      await this.commitTurn(generation, true);
      return;
    }

    this.turn = "idle";
    this.gate?.settle();
    this.gate = null;
    this.options.voice.release();
    this.setPhase("idle");
  }

  /** Called when the current reply audio ends, fails, or is interrupted. */
  notifyPlaybackFinished(): void {
    this.gate?.settle();
  }

  dispose(): void {
    this.generation += 1;
    this.active = false;
    this.stopRequested = true;
    this.turn = "idle";
    this.gate?.settle();
    this.gate = null;
    this.options.voice.release();
  }

  private async listen(generation: number): Promise<void> {
    if (generation !== this.generation || !this.active || this.stopRequested) return;
    this.turn = "opening";
    this.setPhase("listening");
    const started = await this.options.voice.beginTurn();
    if (generation !== this.generation || !this.active || this.stopRequested) {
      // A stop during the opening handshake may have raced with stream setup.
      this.options.voice.release();
      return;
    }
    if (!started) {
      this.finish(generation, "idle");
      return;
    }
    this.turn = "listening";
  }

  /**
   * Opens the next streaming turn while the answer is on its way. It is muted
   * from the first frame, so no partials and no auto-commit happen before the
   * reply audio is over (or interrupted by the user).
   */
  private async openMutedTurn(generation: number): Promise<boolean> {
    if (generation !== this.generation || !this.active || this.stopRequested) return false;
    let started = false;
    try {
      started = await this.options.voice.beginTurn({ muted: true });
    } catch {
      started = false;
    }
    if (generation !== this.generation) return false;
    if (!started) return false;
    if (!this.active || this.stopRequested) {
      this.options.voice.release();
      return false;
    }
    return true;
  }

  private async commitTurn(generation: number, manual: boolean): Promise<void> {
    if (generation !== this.generation) return;
    if (this.turn === "committing" || this.turn === "sending") return;

    const spoke = this.options.hasSpeech ? this.options.hasSpeech() : true;
    this.turn = "committing";
    this.setPhase("thinking");

    const outcome = await this.options.voice.commitTurn();
    if (generation !== this.generation) return;

    if (!this.active || this.stopRequested) {
      // The turn is already stopped; the microphone is no longer needed while
      // the transcript is sent and the reply is announced.
      this.options.voice.release();
    }

    if (outcome.kind === "empty") {
      if (manual || !this.active || this.stopRequested) {
        this.finish(generation, "idle");
        return;
      }
      this.turn = "idle";
      await this.listen(generation);
      return;
    }

    if (outcome.kind === "error") {
      if (!manual && this.active && spoke) {
        this.report("recognition_failed", outcome.message);
        this.options.onError?.(outcome.message);
      }
      this.finish(generation, "idle");
      return;
    }

    const closing = this.isFarewell(outcome.text);
    const gate = createPlaybackGate();
    this.gate = gate;
    this.turn = "sending";

    // Both start in the same tick: the request goes out and the microphone opens
    // the next streaming turn in muted mode while the answer is being produced.
    let sendPromise: Promise<ConversationSendResult>;
    try {
      sendPromise = this.options.sendUtterance(outcome.text, { closing });
    } catch {
      sendPromise = Promise.resolve({ ok: false, hasAudio: false });
    }
    const mutedTurn = closing ? null : this.openMutedTurn(generation);

    let result: ConversationSendResult;
    try {
      result = await sendPromise;
    } catch {
      result = { ok: false, hasAudio: false };
    }
    if (generation !== this.generation) {
      gate.settle();
      return;
    }

    const mutedReady = mutedTurn ? await mutedTurn : false;
    if (generation !== this.generation) {
      gate.settle();
      return;
    }

    if (!this.active || this.stopRequested) {
      gate.settle();
      this.gate = null;
      this.finish(generation, closing ? "ended" : "idle");
      return;
    }

    if (!result.ok) {
      this.report("send_failed", "chat request failed");
      gate.settle();
      this.gate = null;
      if (closing) {
        this.finish(generation, "ended");
        return;
      }
      if (mutedReady) {
        // The mic never closed: carry on in the turn that is already streaming.
        this.resumeListening(generation);
        return;
      }
      this.turn = "idle";
      await this.sleep(this.guardMs);
      if (generation !== this.generation || !this.active || this.stopRequested) return;
      await this.listen(generation);
      return;
    }

    this.turn = mutedReady ? "muted" : "idle";

    if (result.hasAudio) {
      this.setPhase("speaking");
      await this.waitForPlayback(gate);
      if (generation !== this.generation) return;
    }

    gate.settle();
    this.gate = null;

    if (!this.active || this.stopRequested) {
      this.finish(generation, closing ? "ended" : "idle");
      return;
    }
    if (closing) {
      this.finish(generation, "ended");
      return;
    }
    if (mutedReady) {
      // No reopen: the muted turn simply starts forwarding frames again.
      this.resumeListening(generation);
      return;
    }

    // The muted turn could not be opened; reopen a fresh listening turn instead.
    this.turn = "idle";
    await this.sleep(this.guardMs);
    if (generation !== this.generation || !this.active || this.stopRequested) return;
    await this.listen(generation);
  }

  private resumeListening(generation: number): void {
    if (generation !== this.generation || !this.active || this.stopRequested) return;
    this.options.voice.unmute();
    this.turn = "listening";
    this.setPhase("listening");
  }

  private finish(generation: number, phase: ConversationPhase): void {
    if (generation !== this.generation) return;
    this.active = false;
    this.stopRequested = true;
    this.turn = "idle";
    this.gate?.settle();
    this.gate = null;
    this.options.voice.release();
    this.setPhase(phase);
    this.setActive(false);
    if (phase === "ended") this.options.onFarewell?.();
  }

  private sleep(milliseconds: number): Promise<void> {
    if (milliseconds <= 0) return Promise.resolve();
    return (this.options.delay ?? defaultDelay)(milliseconds);
  }

  private waitForPlayback(gate: PlaybackGate): Promise<void> {
    const timeoutMs = this.options.playbackTimeoutMs ?? 120_000;
    return new Promise((resolve) => {
      const timer = globalThis.setTimeout(resolve, timeoutMs);
      void gate.promise.then(() => {
        globalThis.clearTimeout(timer);
        resolve();
      });
    });
  }

  private report(event: string, detail = ""): void {
    try {
      this.options.onTelemetry?.(event, this.phase, detail);
    } catch {
      // Diagnostics must never break the dialogue.
    }
  }

  private setPhase(phase: ConversationPhase): void {
    if (this.phase === phase) return;
    this.phase = phase;
    this.report("phase");
    this.options.onPhase?.(phase);
  }

  private setActive(active: boolean): void {
    this.options.onActiveChange?.(active);
  }
}
