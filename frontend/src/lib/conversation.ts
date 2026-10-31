import { isFarewellUtterance } from "./farewell";

export type ConversationPhase = "idle" | "listening" | "thinking" | "speaking" | "ended";

export type VoiceTurnOutcome =
  | { kind: "text"; text: string }
  | { kind: "empty" }
  | { kind: "error"; message: string };

/** Операции с микрофоном и веб-сокетом одного хода, которые использует цикл. */
export interface VoiceTurnPort {
  /** Захватывает микрофон один раз на весь диалог. */
  open(): Promise<boolean>;
  /**
   * Открывает потоковый ход на уже захваченном микрофоне. Приглушённый ход
   * продолжает снимать кадры локально, но не отправляет их распознавателю.
   */
  beginTurn(options?: { muted?: boolean }): Promise<boolean>;
  /** Завершает ход и возвращает его финальную расшифровку. */
  commitTurn(): Promise<VoiceTurnOutcome>;
  /** Освобождает микрофон при выходе из режима. */
  release(): void;
  /** Возобновляет отправку кадров в уже открытом ходе. */
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
  /** По умолчанию общий детектор прощания. */
  isFarewell?: (text: string) => boolean;
  /** Сообщает, есть ли в текущем ходе настоящая речь. */
  hasSpeech?: () => boolean;
  onPhase?: (phase: ConversationPhase) => void;
  onActiveChange?: (active: boolean) => void;
  onError?: (message: string) => void;
  onFarewell?: () => void;
  /** Необязательная диагностика; получает фазу цикла на момент события. */
  onTelemetry?: (event: string, phase: ConversationPhase, detail: string) => void;
  /** Пауза перед повторным открытием запасного хода прослушивания. */
  guardMs?: number;
  /** Страховка на случай, если колбэк воспроизведения так и не придёт. */
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
 * Диалог без рук, который держит один микрофон и один потоковый ход:
 *
 * слушаем -> завершаем -> отправляем -> думаем (следующий ход открывается
 * приглушённым) -> говорим (приглушённо, перебивание взведено) -> снимаем
 * заглушение -> снова слушаем в том же ходе
 *
 * Ход, открытый приглушённым на время генерации ответа, становится следующим
 * ходом прослушивания: после воспроизведения с него лишь снимается заглушение,
 * поэтому ни микрофон, ни веб-сокет не переоткрываются. Короткое прощание
 * отправляется с `closing: true`, и цикл заканчивается после ответа. Пустой ход
 * начинает слушать заново, а не показывает ошибку; неудачный запрос сохраняет
 * микрофон и возвращается к прослушиванию. Цикл не хранит состояние React.
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

  /** Автозавершение: допустимо только во время хода прослушивания. */
  async commit(): Promise<void> {
    if (!this.active || this.stopRequested || this.turn !== "listening") return;
    await this.commitTurn(this.generation, false);
  }

  /** Ручная остановка: завершить текущий поток, затем выйти из режима. */
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

  /** Вызывается, когда звук ответа закончился, упал или был прерван. */
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
      // Остановка во время открывающего рукопожатия могла обогнать настройку потока.
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
   * Открывает следующий потоковый ход, пока ответ ещё в пути. Ход приглушён с
   * первого кадра, поэтому промежуточных расшифровок и автозавершения нет,
   * пока не закончится (или не будет прерван) звук ответа.
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
      // Ход уже остановлен: микрофон больше не нужен, пока отправляется
      // расшифровка и объявляется ответ.
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

    // Оба стартуют в одном тике: запрос уходит, а микрофон открывает следующий
    // потоковый ход приглушённым, пока генерируется ответ.
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
        // Микрофон не закрывался: продолжаем в уже потоковом ходе.
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
      // Переоткрытия нет: приглушённый ход просто снова начинает слать кадры.
      this.resumeListening(generation);
      return;
    }

    // Приглушённый ход открыть не удалось: открываем новый ход прослушивания.
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
      // Диагностика не должна ломать диалог.
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
