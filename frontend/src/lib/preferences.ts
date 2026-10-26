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

const VOICE_KEY = "assistant.ttsVoice";

/** Выбранный голос озвучки; пустая строка означает голос сервера по умолчанию. */
export function readVoice(): string {
  try {
    return window.localStorage.getItem(VOICE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function writeVoice(value: string): void {
  try {
    if (value) window.localStorage.setItem(VOICE_KEY, value);
    else window.localStorage.removeItem(VOICE_KEY);
  } catch {
    // Приватный режим: выбор живёт до перезагрузки страницы.
  }
}
