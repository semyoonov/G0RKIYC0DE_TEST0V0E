const SPEAK_KEY = "assistant.speakReplies";

/** Озвучивание ответов включено по умолчанию; выбор запоминается в браузере. */
export function readSpeakReplies(): boolean {
  try {
    const raw = window.localStorage.getItem(SPEAK_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

export function writeSpeakReplies(value: boolean): void {
  try {
    window.localStorage.setItem(SPEAK_KEY, value ? "1" : "0");
  } catch {
    // Приватный режим: настройка живёт до перезагрузки страницы.
  }
}
