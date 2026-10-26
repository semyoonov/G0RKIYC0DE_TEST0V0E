import { afterEach, describe, expect, it } from "vitest";

import { readSpeakReplies, readVoice, writeSpeakReplies, writeVoice } from "./preferences";

describe("preferences", () => {
  afterEach(() => {
    window.localStorage.clear();
  });

  it("озвучивание включено по умолчанию", () => {
    expect(readSpeakReplies()).toBe(true);
  });

  it("запоминает выключенное озвучивание", () => {
    writeSpeakReplies(false);
    expect(readSpeakReplies()).toBe(false);
    expect(window.localStorage.getItem("assistant.speakReplies")).toBe("0");
  });

  it("возвращает включённое озвучивание после переключения", () => {
    writeSpeakReplies(false);
    writeSpeakReplies(true);
    expect(readSpeakReplies()).toBe(true);
  });

  it("по умолчанию голос не выбран", () => {
    expect(readVoice()).toBe("");
  });

  it("запоминает выбранный голос и умеет его сбросить", () => {
    writeVoice("Bab-Energetic");
    expect(readVoice()).toBe("Bab-Energetic");
    writeVoice("");
    expect(readVoice()).toBe("");
    expect(window.localStorage.getItem("assistant.ttsVoice")).toBeNull();
  });
});
