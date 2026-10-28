import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MIC_DENIED_TEXT, useVoiceStream } from "./useVoiceStream";

const PREFERRED_CONSTRAINTS = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};
const FALLBACK_CONSTRAINTS = { audio: true };

const getUserMedia = vi.fn<MediaDevices["getUserMedia"]>();
const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");

function fakeMicrophone(): { stream: MediaStream; stop: ReturnType<typeof vi.fn> } {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  return { stream, stop };
}

beforeEach(() => {
  getUserMedia.mockReset();
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
});

afterEach(() => {
  if (originalMediaDevices) {
    Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
  } else {
    delete (navigator as unknown as { mediaDevices?: unknown }).mediaDevices;
  }
});

describe("useVoiceStream microphone constraints", () => {
  it("asks for echo cancellation, noise suppression and auto gain", async () => {
    const { stream, stop } = fakeMicrophone();
    getUserMedia.mockResolvedValueOnce(stream);
    const { result, unmount } = renderHook(() => useVoiceStream());

    await act(async () => {
      expect(await result.current.openMicrophone()).toBe(true);
    });

    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(getUserMedia).toHaveBeenCalledWith(PREFERRED_CONSTRAINTS);

    // The microphone is acquired once for the whole dialogue.
    await act(async () => {
      expect(await result.current.openMicrophone()).toBe(true);
    });
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    unmount();
    expect(stop).toHaveBeenCalled();
  });

  it("falls back to a plain audio request when the constraints are unsupported", async () => {
    getUserMedia
      .mockRejectedValueOnce(
        Object.assign(new Error("constraints"), { name: "OverconstrainedError" }),
      )
      .mockResolvedValueOnce(fakeMicrophone().stream);

    const { result, unmount } = renderHook(() => useVoiceStream());
    await act(async () => {
      expect(await result.current.openMicrophone()).toBe(true);
    });

    expect(getUserMedia).toHaveBeenNthCalledWith(1, PREFERRED_CONSTRAINTS);
    expect(getUserMedia).toHaveBeenNthCalledWith(2, FALLBACK_CONSTRAINTS);
    expect(result.current.error).toBeNull();

    unmount();
  });

  it("reports a denied microphone and does not keep a stream", async () => {
    getUserMedia.mockRejectedValue(
      Object.assign(new Error("denied"), { name: "NotAllowedError" }),
    );

    const { result } = renderHook(() => useVoiceStream());
    await act(async () => {
      expect(await result.current.openMicrophone()).toBe(false);
    });

    expect(result.current.error).toBe(MIC_DENIED_TEXT);
    expect(getUserMedia).toHaveBeenCalledTimes(2);
  });
});
