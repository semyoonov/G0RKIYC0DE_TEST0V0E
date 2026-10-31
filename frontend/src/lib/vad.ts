/**
 * Помощники определения речевой активности, общие для хука захвата и цикла
 * диалога. Всё здесь чистое, время всегда передаётся явно, поэтому решение об
 * автозавершении проверяется на синтетических энергиях и поддельных часах, без
 * настоящего микрофона.
 */

/** Уровень RMS (0..1), начиная с которого кадр 16-битного PCM считается речью. */
export const VAD_ENERGY_THRESHOLD = 0.01;

/** Тишина после последнего речевого кадра, по истечении которой ход завершается. */
export const VAD_SILENCE_MS = 2500;

/** Энергия RMS кадра моно 16-битного PCM. */
export function pcm16Energy(buffer: ArrayBuffer): number {
  const samples = new Int16Array(buffer);
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    const value = samples[index] / 0x8000;
    sum += value * value;
  }
  return Math.sqrt(sum / samples.length);
}

export function isVoicedEnergy(energy: number, threshold = VAD_ENERGY_THRESHOLD): boolean {
  return Number.isFinite(energy) && energy >= threshold;
}

export interface AutoCommitOptions {
  threshold?: number;
  silenceMs?: number;
}

/**
 * Ведёт один ход прослушивания: говорил ли пользователь, пришла ли от сервера
 * промежуточная расшифровка и истекло ли окно тишины с последнего речевого кадра.
 */
export class AutoCommitDetector {
  readonly threshold: number;
  readonly silenceMs: number;

  private spoken = false;
  private lastVoiceAt: number | null = null;
  private partial = "";

  constructor(options: AutoCommitOptions = {}) {
    this.threshold = options.threshold ?? VAD_ENERGY_THRESHOLD;
    this.silenceMs = options.silenceMs ?? VAD_SILENCE_MS;
  }

  get spoke(): boolean {
    return this.spoken;
  }

  get partialText(): string {
    return this.partial;
  }

  reset(): void {
    this.spoken = false;
    this.lastVoiceAt = null;
    this.partial = "";
  }

  setPartial(text: string | null | undefined): void {
    this.partial = (text ?? "").trim();
  }

  /** Учитывает кадр; возвращает true, если его громкости хватило на речь. */
  noteEnergy(energy: number, now: number): boolean {
    if (!Number.isFinite(now) || !isVoicedEnergy(energy, this.threshold)) return false;
    this.spoken = true;
    this.lastVoiceAt = this.lastVoiceAt === null ? now : Math.max(this.lastVoiceAt, now);
    return true;
  }

  /** Ближайший момент, когда может сработать автозавершение; null, пока ход не готов. */
  commitDeadline(): number | null {
    if (!this.spoken || !this.partial || this.lastVoiceAt === null) return null;
    return this.lastVoiceAt + this.silenceMs;
  }

  shouldCommit(now: number): boolean {
    const deadline = this.commitDeadline();
    return deadline !== null && now >= deadline;
  }
}
