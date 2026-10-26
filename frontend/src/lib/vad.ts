/**
 * Voice activity helpers shared by the capture hook and the conversation
 * loop. Everything here is pure and time is always passed in explicitly, so
 * the auto-commit decision can be tested with synthetic energies and a fake
 * clock instead of a real microphone.
 */

/** RMS level (0..1) that counts as speech for a 16-bit PCM frame. */
export const VAD_ENERGY_THRESHOLD = 0.01;

/** Silence after the last voiced frame before a turn is committed. */
export const VAD_SILENCE_MS = 2500;

/** RMS energy of an interleaved mono 16-bit PCM frame. */
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
 * Tracks one listening turn: has the user spoken, has the server produced a
 * partial transcript, and has the silence window elapsed since the last
 * voiced frame.
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

  /** Records a frame; returns true when the frame was loud enough to be speech. */
  noteEnergy(energy: number, now: number): boolean {
    if (!Number.isFinite(now) || !isVoicedEnergy(energy, this.threshold)) return false;
    this.spoken = true;
    this.lastVoiceAt = this.lastVoiceAt === null ? now : Math.max(this.lastVoiceAt, now);
    return true;
  }

  /** Earliest moment auto-commit may fire, or null while the turn is not ready. */
  commitDeadline(): number | null {
    if (!this.spoken || !this.partial || this.lastVoiceAt === null) return null;
    return this.lastVoiceAt + this.silenceMs;
  }

  shouldCommit(now: number): boolean {
    const deadline = this.commitDeadline();
    return deadline !== null && now >= deadline;
  }
}
