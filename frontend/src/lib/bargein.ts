/**
 * Barge-in detection for hands-free playback.
 *
 * While the reply audio is playing the microphone keeps producing frames but
 * they are not sent to the recognizer. Those local RMS values are enough to
 * decide that the user started talking over the assistant: the mean level of a
 * short window has to be speech-like and contain a real peak, so a single click
 * or a cough never interrupts the answer while talking over it does.
 *
 * Pure and clock-injected, so the decision is tested with synthetic energies.
 */

/** Peak RMS that has to appear in the window: a click or a keyboard never gets there. */
export const BARGE_IN_ENERGY_THRESHOLD = 0.05;

/** Mean RMS over the window: speech dips between words, so the average is what counts. */
export const BARGE_IN_MEAN_THRESHOLD = 0.035;

/** The reply audio itself needs a moment to start; its click is not a barge-in. */
export const BARGE_IN_STARTUP_GUARD_MS = 300;

/** Sliding window over which the speech level is averaged. */
export const BARGE_IN_WINDOW_MS = 400;

/** How long the window has to stay loud before playback is interrupted. */
export const BARGE_IN_HOLD_MS = 300;

/** Frames above the mean threshold the window needs: one click is a single frame. */
export const BARGE_IN_MIN_LOUD_FRAMES = 3;

export interface BargeInOptions {
  threshold?: number;
  meanThreshold?: number;
  windowMs?: number;
  holdMs?: number;
}

interface Sample {
  at: number;
  energy: number;
}

export class BargeInDetector {
  readonly threshold: number;
  readonly meanThreshold: number;
  readonly windowMs: number;
  readonly holdMs: number;

  private samples: Sample[] = [];
  private fired = false;

  constructor(options: BargeInOptions = {}) {
    this.threshold = options.threshold ?? BARGE_IN_ENERGY_THRESHOLD;
    this.meanThreshold = options.meanThreshold ?? BARGE_IN_MEAN_THRESHOLD;
    this.windowMs = options.windowMs ?? BARGE_IN_WINDOW_MS;
    this.holdMs = options.holdMs ?? BARGE_IN_HOLD_MS;
  }

  /** True once this detector has fired; only `reset` clears it. */
  get triggered(): boolean {
    return this.fired;
  }

  reset(): void {
    this.samples = [];
    this.fired = false;
  }

  /**
   * Feeds one frame. Speech rises and falls, so the decision uses the mean level of
   * a short window that also has to contain a real peak: a cough or a click never
   * interrupts the answer, talking over it does.
   */
  noteEnergy(energy: number, now: number): boolean {
    if (this.fired) return false;
    if (!Number.isFinite(energy) || !Number.isFinite(now)) {
      this.samples = [];
      return false;
    }
    this.samples.push({ at: now, energy });
    const cutoff = now - this.windowMs;
    while (this.samples.length > 0 && this.samples[0].at < cutoff) this.samples.shift();
    const first = this.samples[0];
    if (!first || now - first.at < this.holdMs) return false;

    let sum = 0;
    let peak = 0;
    let loudFrames = 0;
    for (const sample of this.samples) {
      sum += sample.energy;
      if (sample.energy > peak) peak = sample.energy;
      if (sample.energy >= this.meanThreshold) loudFrames += 1;
    }
    const mean = sum / this.samples.length;
    if (loudFrames < BARGE_IN_MIN_LOUD_FRAMES) return false;
    if (mean < this.meanThreshold || peak < this.threshold) return false;
    this.fired = true;
    return true;
  }
}
