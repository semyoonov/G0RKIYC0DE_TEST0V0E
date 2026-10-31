/**
 * Кэш синтезированной речи в памяти.
 *
 * `/api/speech` стоит 1–3 с на вызов, но один и тот же ответ часто озвучивается
 * повторно (переспрос, быстрые действия, повтор после перебивания или
 * нераспознанной фразы). Небольшой LRU делает такие повторы мгновенными и не
 * трогает контракт бэкенда. Неудачный синтез не кэшируется, на диск ничего не
 * пишется.
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
    // Обновляет порядок давности: Map хранит порядок вставки.
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
