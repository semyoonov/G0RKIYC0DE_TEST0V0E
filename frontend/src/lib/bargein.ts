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
export const BARGE_IN_ENERGY_THRESHOLD = 0.045;

/** How long the input has to stay loud before playback is interrupted. */
export const BARGE_IN_HOLD_MS = 300;

/** Silence drains the accumulated loud time this many times faster than it fills. */
const QUIET_DECAY_FACTOR = 2;

/** Frames arrive every ~40 ms; a longer gap is a stall, not speech. */
const MAX_DELTA_MS = 500;

/** The reply audio itself needs a moment to start; its click is not a barge-in. */
export const BARGE_IN_STARTUP_GUARD_MS = 300;

export interface BargeInOptions {
  threshold?: number;
  holdMs?: number;
}

export class BargeInDetector {
  readonly threshold: number;
  readonly holdMs: number;

  private loudMs = 0;
  private lastAt: number | null = null;
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
    this.loudMs = 0;
    this.lastAt = null;
    this.fired = false;
  }

  /**
   * Feeds one frame. Speech energy rises and falls, so loud time accumulates and
   * silence drains it twice as fast instead of resetting the burst: a click or a
   * gap between words never cancels the interruption, a cough never triggers it.
   */
  noteEnergy(energy: number, now: number): boolean {
    if (this.fired) return false;
    if (!Number.isFinite(energy) || !Number.isFinite(now)) {
      this.reset();
      return false;
    }
    const delta = this.lastAt === null ? 0 : Math.max(0, Math.min(MAX_DELTA_MS, now - this.lastAt));
    this.lastAt = now;
    if (energy >= this.threshold) this.loudMs += delta;
    else this.loudMs = Math.max(0, this.loudMs - delta * QUIET_DECAY_FACTOR);
    if (this.loudMs < this.holdMs) return false;
    this.fired = true;
    return true;
  }
}
