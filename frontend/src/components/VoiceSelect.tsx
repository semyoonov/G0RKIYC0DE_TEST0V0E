interface VoiceSelectProps {
  voices: string[];
  value: string;
  disabled?: boolean;
  onChange: (voice: string) => void;
}

/** Голос озвучки: список приходит с сервера, выбор запоминается в браузере. */
export function VoiceSelect({ voices, value, disabled = false, onChange }: VoiceSelectProps) {
  if (voices.length === 0) return null;
  return (
    <label className="inline-flex shrink-0 items-center gap-2 rounded-full border border-line px-3 py-1.5 text-xs text-ink-muted">
      <span className="text-ink-dim">Голос</span>
      <select
        value={value || voices[0]}
        aria-label="Голос озвучки"
        disabled={disabled || voices.length === 1}
        onChange={(event) => onChange(event.target.value)}
        className="max-w-[9.5rem] bg-transparent text-xs text-ink outline-none disabled:opacity-60"
      >
        {voices.map((voice) => (
          <option key={voice} value={voice} className="bg-panel text-ink">
            {voice}
          </option>
        ))}
      </select>
    </label>
  );
}
