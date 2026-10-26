/**
 * Barge-in detection for hands-free playback.
 *
 * While the reply audio is playing the microphone keeps producing frames but
 * they are not sent to the recognizer. Those local RMS values are enough to
 * decide that the user started talking over the assistant: the energy has to
 * stay above a higher-than-speech threshold for a short while, so a single
 * click or a cough never interrupts the answer.
 *
 * Pure and clock-injected, so the decision is tested with synthetic energies.
 */

/** RMS level (0..1) that counts as talking over the reply audio. */
export const BARGE_IN_ENERGY_THRESHOLD = 0.05;

/** How long the input has to stay loud before playback is interrupted. */
export const BARGE_IN_HOLD_MS = 250;

export interface BargeInOptions {
  threshold?: number;
  holdMs?: number;
}

export class BargeInDetector {
  readonly threshold: number;
  readonly holdMs: number;

  private since: number | null = null;
  private fired = false;

  constructor(options: BargeInOptions = {}) {
    this.threshold = options.threshold ?? BARGE_IN_ENERGY_THRESHOLD;
    this.holdMs = options.holdMs ?? BARGE_IN_HOLD_MS;
  }

  /** True once this detector has fired; only `reset` clears it. */
  get triggered(): boolean {
    return this.fired;
  }

  reset(): void {
    this.since = null;
    this.fired = false;
  }

  /**
   * Feeds one frame. Returns true exactly once per sustained burst: a quiet
   * frame ends the burst, so an isolated loud click never triggers barge-in.
   */
  noteEnergy(energy: number, now: number): boolean {
    if (this.fired) return false;
    if (!Number.isFinite(energy) || !Number.isFinite(now) || energy < this.threshold) {
      this.since = null;
      return false;
    }
    if (this.since === null || now < this.since) {
      this.since = now;
      return false;
    }
    if (now - this.since < this.holdMs) return false;
    this.fired = true;
    this.since = null;
    return true;
  }
}
