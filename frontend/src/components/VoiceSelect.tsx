interface VoiceSelectProps {
  voices: string[];
  value: string;
  disabled?: boolean;
  onChange: (voice: string) => void;
}

/**
 * Голос озвучки: список приходит с сервера, выбор запоминается в браузере.
 * Виден всегда; пока список не пришёл, предлагает голос сервера по умолчанию.
 */
export function VoiceSelect({ voices, value, disabled = false, onChange }: VoiceSelectProps) {
  const hasCatalogue = voices.length > 0;
  return (
    // Высота совпадает с переключателем «Текстом | Голосом», рядом с которым стоит.
    <label
      className={`inline-flex h-9 min-w-0 flex-1 items-center gap-2 rounded-full border border-line bg-card px-3 text-[13px] text-ink-muted transition-opacity sm:flex-none ${
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
      }`}
    >
      {/* На узком экране подпись прячем: место нужно самому списку. */}
      <span className="hidden shrink-0 text-ink-dim sm:inline">Голос</span>
      <select
        value={hasCatalogue ? value || voices[0] : ""}
        aria-label="Голос озвучки"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full min-w-0 bg-transparent text-[13px] text-ink outline-none disabled:cursor-not-allowed sm:w-auto sm:max-w-[9.5rem]"
      >
        {hasCatalogue ? (
          voices.map((voice) => (
            <option key={voice} value={voice} className="bg-panel text-ink">
              {voice}
            </option>
          ))
        ) : (
          <option value="" className="bg-panel text-ink">
            Стандартный
          </option>
        )}
      </select>
    </label>
  );
}
