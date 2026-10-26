import { describe, expect, it } from "vitest";

import {
  BARGE_IN_ENERGY_THRESHOLD,
  BARGE_IN_HOLD_MS,
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

describe("barge-in constants", () => {
  it("sits clearly above the speech threshold", () => {
    expect(BARGE_IN_ENERGY_THRESHOLD).toBeGreaterThan(VAD_ENERGY_THRESHOLD);
    expect(BARGE_IN_HOLD_MS).toBeGreaterThanOrEqual(250);
  });
});

describe("BargeInDetector", () => {
  it("never fires on quiet input", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();
    for (let index = 0; index < 200; index += 1) {
      clock.advance(40);
      expect(detector.noteEnergy(0.02, clock.now)).toBe(false);
    }
    expect(detector.triggered).toBe(false);
  });

  it("ignores a single click even when it is loud", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();

    expect(detector.noteEnergy(0.4, clock.now)).toBe(false);
    for (let index = 0; index < 50; index += 1) {
      clock.advance(40);
      expect(detector.noteEnergy(0.001, clock.now)).toBe(false);
    }

    expect(detector.triggered).toBe(false);
  });

  it("does not fire while the loud burst is shorter than the hold window", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();

    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    clock.advance(200);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    expect(detector.triggered).toBe(false);
  });

  it("fires once the input stays loud for the hold window", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();

    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    clock.advance(BARGE_IN_HOLD_MS - 1);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    clock.advance(1);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(true);

    // One interruption per burst: further frames are ignored until reset.
    clock.advance(40);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    expect(detector.triggered).toBe(true);
  });

  it("restarts the window after a quiet frame", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();

    detector.noteEnergy(0.08, clock.now);
    clock.advance(240);
    expect(detector.noteEnergy(0.001, clock.now)).toBe(false);
    clock.advance(40);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    clock.advance(240);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(false);
    clock.advance(10);
    expect(detector.noteEnergy(0.08, clock.now)).toBe(true);
  });

  it("ignores non-finite values and re-arms after reset", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector();

    expect(detector.noteEnergy(Number.NaN, clock.now)).toBe(false);
    expect(detector.noteEnergy(0.5, Number.NaN)).toBe(false);

    detector.noteEnergy(0.2, clock.now);
    clock.advance(BARGE_IN_HOLD_MS);
    expect(detector.noteEnergy(0.2, clock.now)).toBe(true);

    detector.reset();
    expect(detector.triggered).toBe(false);
    expect(detector.noteEnergy(0.2, clock.now)).toBe(false);
    clock.advance(BARGE_IN_HOLD_MS);
    expect(detector.noteEnergy(0.2, clock.now)).toBe(true);
  });

  it("supports custom threshold and hold options", () => {
    const clock = fakeClock();
    const detector = new BargeInDetector({ threshold: 0.2, holdMs: 100 });

    expect(detector.noteEnergy(0.1, clock.now)).toBe(false);
    expect(detector.noteEnergy(0.25, clock.now)).toBe(false);
    clock.advance(100);
    expect(detector.noteEnergy(0.25, clock.now)).toBe(true);
  });
});
