import { describe, expect, it } from "vitest";

import {
  BARGE_IN_ENERGY_THRESHOLD,
  BARGE_IN_HOLD_MS,
  BARGE_IN_MEAN_THRESHOLD,
  BARGE_IN_WINDOW_MS,
  BargeInDetector,
} from "./bargein";
import { VAD_ENERGY_THRESHOLD } from "./vad";

function fakeClock(start = 1_000) {
  let current = start;
  return {
    get now() {
      return current;
    },
    advance(milliseconds: number) {
      current += milliseconds;
      return current;
    },
  };
}

/** Подаёт `count` кадров с энергией `energy` с шагом в один кадр. */
function feed(detector: BargeInDetector, clock: ReturnType<typeof fakeClock>, energy: number, count: number, step = 40) {
  let fired = false;
  for (let index = 0; index < count; index += 1) {
    clock.advance(step);
    if (detector.noteEnergy(energy, clock.now)) fired = true;
  }
  return fired;
}

describe("barge-in constants", () => {
  it("sits above the speech threshold and below a shout", () => {
    expect(BARGE_IN_ENERGY_THRESHOLD).toBeGreaterThan(VAD_ENERGY_THRESHOLD);
    expect(BARGE_IN_MEAN_THRESHOLD).toBeLessThan(BARGE_IN_ENERGY_THRESHOLD);
    expect(BARGE_IN_HOLD_MS).toBeGreaterThanOrEqual(250);
    expect(BARGE_IN_WINDOW_MS).toBeGreaterThan(BARGE_IN_HOLD_MS);
  });
});

describe("BargeInDetector", () => {
  it("never fires on quiet input", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    expect(feed(detector, clock, 0.02, 200)).toBe(false);
    expect(detector.triggered).toBe(false);
  });

  it("ignores a single loud click", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    expect(feed(detector, clock, 0.4, 1)).toBe(false);
    expect(feed(detector, clock, 0.001, 50)).toBe(false);
    expect(detector.triggered).toBe(false);
  });

  it("fires on speech that dips between words", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    let fired = false;
    for (let index = 0; index < 20; index += 1) {
      if (feed(detector, clock, index % 2 === 0 ? 0.09 : 0.005, 1)) fired = true;
    }
    expect(fired).toBe(true);
  });

  it("does not fire before the window has lasted long enough", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    expect(feed(detector, clock, 0.09, 5)).toBe(false);
    expect(detector.triggered).toBe(false);
  });

  it("fires once, then stays quiet until reset", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    expect(feed(detector, clock, 0.09, 20)).toBe(true);
    expect(feed(detector, clock, 0.09, 20)).toBe(false);
    expect(detector.triggered).toBe(true);

    detector.reset();
    expect(detector.triggered).toBe(false);
    expect(feed(detector, clock, 0.09, 20)).toBe(true);
  });

  it("ignores non-finite values", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    expect(detector.noteEnergy(Number.NaN, clock.now)).toBe(false);
    expect(detector.noteEnergy(0.5, Number.NaN)).toBe(false);
    expect(detector.triggered).toBe(false);
  });

  it("supports custom thresholds", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector({ threshold: 0.2, meanThreshold: 0.1, holdMs: 100, windowMs: 200 });
    expect(feed(detector, clock, 0.1, 20)).toBe(false);
    expect(feed(detector, clock, 0.25, 20)).toBe(true);
  });
});
