import vkBridge from "@vkontakte/vk-bridge";

export type Platform = "telegram" | "max" | "vk" | "web";

export interface PlatformLaunch {
  platform: Platform;
  payload: string | null;
}

export const PLATFORM_TITLES: Record<Platform, string> = {
  telegram: "Telegram",
  vk: "ВКонтакте",
  max: "MAX",
  web: "Веб",
};

interface StorageLike {
  getItem(key: string): string | null;
}

export interface LaunchEnvironment {
  search?: string;
  hash?: string;
  storage?: StorageLike | null;
  navigationName?: string | null;
  telegramInitData?: string | null;
  maxInitData?: string | null;
}

export interface TelegramWebApp {
  initData?: string;
  ready?: () => void;
  expand?: () => void;
}

export interface MaxWebApp {
  initData?: string;
}

export interface PlatformRuntime {
  telegram?: TelegramWebApp | null;
  sendVkInit?: () => unknown;
}

const MAX_STORAGE_KEY = "WebAppData";
const MAX_FRAGMENT_MARKER = "WebAppData=";

let vkBridgeInitialized = false;

function nonEmpty(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  return value.trim() ? value : null;
}

function readStorage(): StorageLike | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function readMaxInitData(): string | null {
  if (typeof window === "undefined") return null;
  const runtime = window as Window & { WebApp?: MaxWebApp };
  return nonEmpty(runtime.WebApp?.initData);
}

function readTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  const runtime = window as Window & { Telegram?: { WebApp?: TelegramWebApp } };
  return runtime.Telegram?.WebApp ?? null;
}

export function readLaunchEnvironment(): LaunchEnvironment {
  if (typeof window === "undefined") return {};
  let navigationName: string | null = null;
  try {
    const [entry] = window.performance.getEntriesByType("navigation");
    navigationName = entry?.name ?? null;
  } catch {
    navigationName = null;
  }
  return {
    search: window.location.search,
    hash: window.location.hash,
    storage: readStorage(),
    navigationName,
    telegramInitData: nonEmpty(readTelegramWebApp()?.initData),
    maxInitData: readMaxInitData(),
  };
}

function readPairs(raw: string | undefined): Array<[string, string]> {
  if (!raw) return [];
  const text = raw.replace(/^[?#]/, "");
  if (!text) return [];
  try {
    return Array.from(new URLSearchParams(text).entries());
  } catch {
    return [];
  }
}

function readStorageValue(storage: StorageLike | null | undefined, key: string): string | null {
  if (!storage) return null;
  try {
    return nonEmpty(storage.getItem(key));
  } catch {
    return null;
  }
}

/**
 * The MAX bridge puts the URL-encoded launch string after `#WebAppData=`. The
 * value is returned without percent-decoding so the server decodes it exactly
 * once when it validates the signature.
 */
export function readMaxFragmentPayload(fragment: string | null | undefined): string | null {
  if (!fragment) return null;
  const index = fragment.indexOf(MAX_FRAGMENT_MARKER);
  if (index < 0) return null;
  return nonEmpty(fragment.slice(index + MAX_FRAGMENT_MARKER.length));
}

function readMaxPayload(environment: LaunchEnvironment): string | null {
  return (
    nonEmpty(environment.maxInitData) ??
    readMaxFragmentPayload(environment.hash) ??
    readStorageValue(environment.storage, MAX_STORAGE_KEY) ??
    readMaxFragmentPayload(environment.navigationName)
  );
}

function readVkPairs(environment: LaunchEnvironment): Array<[string, string]> {
  const selected = new Map<string, string>();
  for (const raw of [environment.search, environment.hash]) {
    for (const [key, value] of readPairs(raw)) {
      if (key === "sign" || key.startsWith("vk_")) {
        selected.set(key, value);
      }
    }
  }
  return Array.from(selected.entries());
}

function hasVkLaunch(environment: LaunchEnvironment): boolean {
  return readVkPairs(environment).some(([key]) => key.startsWith("vk_"));
}

export function detectPlatform(environment: LaunchEnvironment = readLaunchEnvironment()): Platform {
  if (nonEmpty(environment.telegramInitData)) return "telegram";
  if (readMaxPayload(environment)) return "max";
  if (hasVkLaunch(environment)) return "vk";
  return "web";
}

export function getLaunchPayload(
  platform: Platform,
  environment: LaunchEnvironment = readLaunchEnvironment(),
): string | null {
  if (platform === "telegram") return nonEmpty(environment.telegramInitData);
  if (platform === "max") return readMaxPayload(environment);
  if (platform === "vk") {
    const pairs = readVkPairs(environment);
    if (pairs.length === 0) return null;
    const query = new URLSearchParams();
    for (const [key, value] of pairs) query.append(key, value);
    return query.toString();
  }
  return null;
}

export function detectLaunch(environment: LaunchEnvironment = readLaunchEnvironment()): PlatformLaunch {
  const platform = detectPlatform(environment);
  return { platform, payload: getLaunchPayload(platform, environment) };
}

function readPlatformRuntime(): PlatformRuntime {
  return {
    telegram: readTelegramWebApp(),
    sendVkInit: () => vkBridge.send("VKWebAppInit"),
  };
}

/** Announces the mini app to its client exactly once; plain web pages are left alone. */
export function initializePlatform(
  platform: Platform,
  runtime: PlatformRuntime = readPlatformRuntime(),
): void {
  if (platform === "telegram") {
    const app = runtime.telegram;
    try {
      app?.ready?.();
      app?.expand?.();
    } catch {
      // Telegram SDK failures must not block the web fallback.
    }
    return;
  }
  if (platform === "vk" && !vkBridgeInitialized) {
    vkBridgeInitialized = true;
    try {
      void Promise.resolve(runtime.sendVkInit?.()).catch(() => {});
    } catch {
      // VK bridge is unavailable outside the VK client.
    }
  }
}
