/**
 * A hands-free dialogue can be closed by a short spoken goodbye. The backend
 * accepts a `closing` flag on the final chat message so it can answer with a
 * farewell instead of asking a follow-up question.
 */
export const FAREWELL_MAX_WORDS = 4;

const FAREWELL_WORDS = new Set([
  "спасибо",
  "спс",
  "благодарю",
  "пока",
  "прощай",
  "хватит",
  "отбой",
]);

const FAREWELL_PHRASES: ReadonlyArray<ReadonlyArray<string>> = [
  ["до", "свидания"],
  ["до", "связи"],
  ["до", "встречи"],
  ["всего", "доброго"],
  ["все", "хорошего"],
  ["на", "этом", "все"],
  ["все", "на", "этом"],
  ["на", "сегодня", "все"],
  ["закончили"],
  ["завершаем"],
  ["это", "все"],
];

/** Lower-cased words without punctuation, with ё folded to е. */
export function farewellWords(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/u)
    .filter((word) => word.length > 0);
}

function containsPhrase(words: readonly string[], phrase: readonly string[]): boolean {
  if (phrase.length === 0 || phrase.length > words.length) return false;
  for (let start = 0; start <= words.length - phrase.length; start += 1) {
    if (phrase.every((word, offset) => words[start + offset] === word)) return true;
  }
  return false;
}

/**
 * True for a short farewell such as «спасибо», «до свидания» or «на этом всё».
 * Longer sentences are never treated as a closing utterance.
 */
export function isFarewellUtterance(text: string): boolean {
  const words = farewellWords(text);
  if (words.length === 0 || words.length > FAREWELL_MAX_WORDS) return false;
  if (words.some((word) => FAREWELL_WORDS.has(word))) return true;
  return FAREWELL_PHRASES.some((phrase) => containsPhrase(words, phrase));
}
