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

  it("stays on screen with the server default voice until the catalogue arrives", () => {
    render(<VoiceSelect voices={[]} value="Kaz-Lifelike" onChange={vi.fn()} />);

    const select = screen.getByLabelText("Голос озвучки") as HTMLSelectElement;
    expect(select).toBeEnabled();
    expect(select.value).toBe("");
    expect([...select.options].map((option) => option.textContent)).toEqual(["Стандартный"]);
  });

  it("locks the picker only when replies are text-only", () => {
    const { rerender } = render(
      <VoiceSelect voices={["Mer-Operator"]} value="" disabled onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("Голос озвучки")).toBeDisabled();

    rerender(<VoiceSelect voices={["Mer-Operator"]} value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText("Голос озвучки")).toBeEnabled();
  });
});
