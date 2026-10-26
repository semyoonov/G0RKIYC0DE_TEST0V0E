import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VoiceSelect } from "./VoiceSelect";

const VOICES = ["Mer-Operator", "Kaz-Lifelike", "Bab-Energetic"];

describe("VoiceSelect", () => {
  it("renders every voice and reports the choice", () => {
    const onChange = vi.fn();
    render(<VoiceSelect voices={VOICES} value="Mer-Operator" onChange={onChange} />);

    const select = screen.getByLabelText("Голос озвучки") as HTMLSelectElement;
    expect(select.value).toBe("Mer-Operator");
    expect([...select.options].map((option) => option.value)).toEqual(VOICES);

    fireEvent.change(select, { target: { value: "Bab-Energetic" } });
    expect(onChange).toHaveBeenCalledWith("Bab-Energetic");
  });

  it("shows nothing without a catalogue", () => {
    const { container } = render(<VoiceSelect voices={[]} value="" onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("locks the picker when only one voice is available", () => {
    render(<VoiceSelect voices={["Mer-Operator"]} value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText("Голос озвучки")).toBeDisabled();
  });
});
