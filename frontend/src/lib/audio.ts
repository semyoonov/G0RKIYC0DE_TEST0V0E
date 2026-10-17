export function decodeAudio(data: string, mime: string | null): string | null {
  try {
    const binary = window.atob(data);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return URL.createObjectURL(new Blob([bytes], { type: mime || "audio/ogg" }));
  } catch {
    return null;
  }
}
