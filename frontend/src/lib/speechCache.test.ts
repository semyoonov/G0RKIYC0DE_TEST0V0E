import { describe, expect, it } from "vitest";

import {
  SPEECH_CACHE_MAX_CHARS,
  SPEECH_CACHE_MAX_ENTRIES,
  SpeechCache,
  speechCacheKey,
} from "./speechCache";

describe("speechCacheKey", () => {
  it("separates texts and voices", () => {
    expect(speechCacheKey("Привет", "v1")).not.toBe(speechCacheKey("Привет", "v2"));
    expect(speechCacheKey("Привет", "")).not.toBe(speechCacheKey("Пока", ""));
  });
});

describe("SpeechCache", () => {
  it("returns stored audio and misses unknown keys", () => {
    const cache = new SpeechCache();
    cache.set("a", { audio: "AAA", mime: "audio/ogg" });

    expect(cache.get("a")).toEqual({ audio: "AAA", mime: "audio/ogg" });
    expect(cache.get("missing")).toBeUndefined();
  });

  it("never stores an empty audio payload", () => {
    const cache = new SpeechCache();
    cache.set("empty", { audio: "", mime: null });

    expect(cache.size).toBe(0);
    expect(cache.get("empty")).toBeUndefined();
  });

  it("evicts the least recently used entry beyond the entry cap", () => {
    const cache = new SpeechCache();
    for (let index = 0; index < SPEECH_CACHE_MAX_ENTRIES; index += 1) {
      cache.set(`k${index}`, { audio: "A", mime: null });
    }
    expect(cache.size).toBe(SPEECH_CACHE_MAX_ENTRIES);

    // Обращение к k0 делает k1 самой давней записью.
    expect(cache.get("k0")).toBeDefined();
    cache.set("extra", { audio: "A", mime: null });

    expect(cache.size).toBe(SPEECH_CACHE_MAX_ENTRIES);
    expect(cache.get("k0")).toBeDefined();
    expect(cache.get("k1")).toBeUndefined();
  });

  it("keeps the total audio size within the budget", () => {
    const cache = new SpeechCache();
    const chunk = "x".repeat(Math.ceil(SPEECH_CACHE_MAX_CHARS / 2) + 1);

    cache.set("big1", { audio: chunk, mime: null });
    cache.set("big2", { audio: chunk, mime: null });

    expect(cache.size).toBe(1);
    expect(cache.get("big2")).toBeDefined();
    expect(cache.get("big1")).toBeUndefined();
    expect(cache.totalChars).toBeLessThanOrEqual(SPEECH_CACHE_MAX_CHARS);
  });

  it("replaces the same key without double counting and clears", () => {
    const cache = new SpeechCache();
    cache.set("a", { audio: "AAA", mime: null });
    cache.set("a", { audio: "AAAAA", mime: null });

    expect(cache.size).toBe(1);
    expect(cache.totalChars).toBe(5);

    cache.delete("a");
    expect(cache.size).toBe(0);
    expect(cache.totalChars).toBe(0);

    cache.set("b", { audio: "B", mime: null });
    cache.clear();
    expect(cache.size).toBe(0);
    expect(cache.totalChars).toBe(0);
  });
});
