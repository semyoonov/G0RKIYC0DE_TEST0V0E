/**
 * Детектор перебивания для воспроизведения в режиме без рук.
 *
 * Пока звучит ответ, микрофон продолжает выдавать кадры, но в распознаватель
 * они не уходят. Этих локальных значений RMS достаточно, чтобы понять, что
 * пользователь заговорил поверх ассистента: средний уровень короткого окна
 * должен быть речевым и содержать настоящий пик, поэтому одиночный щелчок или
 * кашель ответ не прерывает, а речь поверх — прерывает.
 *
 * Код чистый, часы внедряются извне: решение проверяется на синтетических энергиях.
 */

/** Пиковый RMS, который обязан появиться в окне: щелчок или клавиатура до него не дотягивают. */
export const BARGE_IN_ENERGY_THRESHOLD = 0.05;

/** Средний RMS по окну: речь проседает между словами, поэтому решает среднее. */
export const BARGE_IN_MEAN_THRESHOLD = 0.035;

/** Самому аудио ответа нужно время на старт: его щелчок — не перебивание. */
export const BARGE_IN_STARTUP_GUARD_MS = 300;

/** Скользящее окно, по которому усредняется уровень речи. */
export const BARGE_IN_WINDOW_MS = 400;

/** Сколько окно должно продержаться громким, прежде чем воспроизведение прервётся. */
export const BARGE_IN_HOLD_MS = 300;

/** Сколько кадров выше среднего порога нужно окну: щелчок даёт всего один кадр. */
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

  /** true после срабатывания; очищается только через `reset`. */
  get triggered(): boolean {
    return this.fired;
  }

  reset(): void {
    this.samples = [];
    this.fired = false;
  }

  /**
   * Принимает один кадр. Речь нарастает и затухает, поэтому решение принимается
   * по среднему уровню короткого окна, в котором обязан быть настоящий пик:
   * кашель или щелчок ответ не прерывают, а речь поверх — прерывает.
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
