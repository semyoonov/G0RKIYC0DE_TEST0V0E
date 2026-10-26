/**
 * In-memory cache for synthesised speech.
 *
 * `/api/speech` costs 1–3 s per call, but the same answer is often voiced
 * again (repeats, quick actions, replays after a barge-in or a missed phrase).
 * A small LRU keeps those instant without touching the backend contract.
 * Audio is never cached when synthesis failed and never persisted to disk.
 */

export interface CachedSpeech {
  audio: string;
  mime: string | null;
  format?: string | null;
}

export const SPEECH_CACHE_MAX_ENTRIES = 12;
export const SPEECH_CACHE_MAX_CHARS = 2_000_000;

export function speechCacheKey(text: string, voice: string): string {
  return `${voice}\u0000${text}`;
}

export class SpeechCache {
  private readonly entries = new Map<string, CachedSpeech>();
  private charCount = 0;

  get size(): number {
    return this.entries.size;
  }

  get totalChars(): number {
    return this.charCount;
  }

  get(key: string): CachedSpeech | undefined {
    const hit = this.entries.get(key);
    if (!hit) return undefined;
    // Refresh the recency order: the Map keeps insertion order.
    this.entries.delete(key);
    this.entries.set(key, hit);
    return hit;
  }

  set(key: string, value: CachedSpeech): void {
    if (!value.audio) return;
    const previous = this.entries.get(key);
    if (previous) {
      this.entries.delete(key);
      this.charCount -= previous.audio.length;
    }
    this.entries.set(key, value);
    this.charCount += value.audio.length;
    while (
      this.entries.size > SPEECH_CACHE_MAX_ENTRIES ||
      this.charCount > SPEECH_CACHE_MAX_CHARS
    ) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.remove(oldest);
    }
  }

  delete(key: string): void {
    this.remove(key);
  }

  clear(): void {
    this.entries.clear();
    this.charCount = 0;
  }

  private remove(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    this.entries.delete(key);
    this.charCount -= entry.audio.length;
  }
}
