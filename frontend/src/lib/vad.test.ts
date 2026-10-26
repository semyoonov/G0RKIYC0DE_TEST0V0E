import { describe, expect, it } from "vitest";

import {
  AutoCommitDetector,
  isVoicedEnergy,
  pcm16Energy,
  VAD_ENERGY_THRESHOLD,
  VAD_SILENCE_MS,
} from "./vad";

function pcmBuffer(samples: number[]): ArrayBuffer {
  return new Int16Array(samples).buffer;
}

function fakeClock(start = 0) {
  let current = start;
  return {
    get now() {
      return current;
    },
    advance(milliseconds: number) {
      current += milliseconds;
      return current;
    },
    set(value: number) {
      current = value;
      return current;
    },
  };
}

describe("pcm16Energy", () => {
  it("returns zero for digital silence", () => {
    expect(pcm16Energy(pcmBuffer(new Array(640).fill(0)))).toBe(0);
  });

  it("returns the normalized RMS of the frame", () => {
    expect(pcm16Energy(pcmBuffer(new Array(640).fill(32767)))).toBeCloseTo(0.99997, 4);
    expect(pcm16Energy(pcmBuffer(new Array(640).fill(16384)))).toBeCloseTo(0.5, 3);
    expect(pcm16Energy(pcmBuffer([]))).toBe(0);
  });
});

describe("isVoicedEnergy", () => {
  it("uses an inclusive threshold and rejects non-finite values", () => {
    expect(isVoicedEnergy(VAD_ENERGY_THRESHOLD)).toBe(true);
    expect(isVoicedEnergy(VAD_ENERGY_THRESHOLD - 0.001)).toBe(false);
    expect(isVoicedEnergy(Number.NaN)).toBe(false);
    expect(isVoicedEnergy(Number.POSITIVE_INFINITY)).toBe(false);
  });
});

describe("AutoCommitDetector", () => {
  it("never commits a silent turn, even with a partial transcript", () => {
    const clock = fakeClock();
    const detector = new AutoCommitDetector();
    for (let index = 0; index < 250; index += 1) {
      clock.advance(40);
      detector.noteEnergy(0.003, clock.now);
    }
    detector.setPartial("что-то похожее на речь");
    expect(detector.spoke).toBe(false);
    expect(detector.commitDeadline()).toBeNull();
    expect(detector.shouldCommit(clock.now + 60_000)).toBe(false);
  });

  it("commits 2.5 seconds after the last voiced frame once a partial exists", () => {
    const clock = fakeClock(10_000);
    const detector = new AutoCommitDetector();
    detector.setPartial("поставь задачу");
    expect(detector.noteEnergy(0.05, clock.now)).toBe(true);

    expect(detector.commitDeadline()).toBe(12_500);
    expect(detector.silenceMs).toBe(VAD_SILENCE_MS);

    clock.advance(2_499);
    expect(detector.shouldCommit(clock.now)).toBe(false);
    clock.advance(1);
    expect(detector.shouldCommit(clock.now)).toBe(true);
  });

  it("waits for the server partial before committing", () => {
    const detector = new AutoCommitDetector();
    detector.noteEnergy(0.05, 0);
    expect(detector.shouldCommit(10_000)).toBe(false);
    detector.setPartial("поставь задачу");
    expect(detector.shouldCommit(10_000)).toBe(true);
  });

  it("moves the deadline when the user speaks again", () => {
    const detector = new AutoCommitDetector();
    detector.setPartial("поставь задачу");
    detector.noteEnergy(0.05, 0);
    detector.noteEnergy(0.06, 2_000);
    expect(detector.shouldCommit(4_499)).toBe(false);
    expect(detector.shouldCommit(4_500)).toBe(true);
  });

  it("ignores frames below the energy threshold", () => {
    const detector = new AutoCommitDetector();
    detector.setPartial("поставь задачу");
    detector.noteEnergy(0.05, 0);
    expect(detector.noteEnergy(0.009, 2_000)).toBe(false);
    expect(detector.shouldCommit(2_500)).toBe(true);
  });

  it("supports custom threshold and silence options", () => {
    const detector = new AutoCommitDetector({ threshold: 0.2, silenceMs: 1_000 });
    detector.setPartial("текст");
    expect(detector.noteEnergy(0.15, 0)).toBe(false);
    expect(detector.spoke).toBe(false);
    expect(detector.noteEnergy(0.25, 500)).toBe(true);
    expect(detector.shouldCommit(1_499)).toBe(false);
    expect(detector.shouldCommit(1_500)).toBe(true);
  });

  it("clears all turn state on reset", () => {
    const detector = new AutoCommitDetector();
    detector.setPartial("текст");
    detector.noteEnergy(0.05, 0);
    detector.reset();
    expect(detector.spoke).toBe(false);
    expect(detector.partialText).toBe("");
    expect(detector.commitDeadline()).toBeNull();
    expect(detector.shouldCommit(60_000)).toBe(false);
  });

  it("trims the partial and does not let it move the deadline", () => {
    const detector = new AutoCommitDetector();
    detector.noteEnergy(0.05, 100);
    detector.setPartial("  привет  ");
    expect(detector.partialText).toBe("привет");
    expect(detector.commitDeadline()).toBe(2_600);
  });
});
