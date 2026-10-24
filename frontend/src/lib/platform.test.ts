import { describe, expect, it, vi } from "vitest";

import {
  detectLaunch,
  detectPlatform,
  getLaunchPayload,
  initializePlatform,
  readMaxFragmentPayload,
} from "./platform";

const MAX_RAW = "auth_date=1700000000&hash=abc123&user=%7B%22id%22%3A7%7D";
const TELEGRAM_RAW = "auth_date=1700000000&hash=tg123&user=%7B%22id%22%3A11%7D";

describe("detectLaunch", () => {
  it("uses Telegram WebApp initData", () => {
    expect(detectLaunch({ telegramInitData: TELEGRAM_RAW })).toEqual({
      platform: "telegram",
      payload: TELEGRAM_RAW,
    });
  });

  it("returns the web platform when no launch data is present", () => {
    expect(detectLaunch({ search: "?utm_source=link", hash: "" })).toEqual({
      platform: "web",
      payload: null,
    });
  });

  it("reads MAX launch data from the bridge without re-encoding it", () => {
    expect(detectLaunch({ maxInitData: MAX_RAW })).toEqual({ platform: "max", payload: MAX_RAW });
  });

  it("reads MAX launch data from the URL fragment without decoding it twice", () => {
    expect(detectLaunch({ hash: `#WebAppData=${MAX_RAW}` })).toEqual({
      platform: "max",
      payload: MAX_RAW,
    });
  });

  it("falls back to sessionStorage for MAX launch data", () => {
    const storage = { getItem: (key: string) => (key === "WebAppData" ? MAX_RAW : null) };
    expect(detectPlatform({ storage })).toBe("max");
    expect(getLaunchPayload("max", { storage })).toBe(MAX_RAW);
  });

  it("falls back to the navigation entry for MAX launch data", () => {
    const navigationName = `https://app.example/#WebAppData=${MAX_RAW}`;
    expect(detectLaunch({ navigationName })).toEqual({ platform: "max", payload: MAX_RAW });
  });

  it("collects VK launch pairs with the signature", () => {
    const launch = detectLaunch({
      search: "?vk_user_id=42&vk_app_id=1&sign=abc&utm_source=vk",
      hash: "#vk_language=ru",
    });

    expect(launch.platform).toBe("vk");
    expect(launch.payload).toBe("vk_user_id=42&vk_app_id=1&sign=abc&vk_language=ru");
  });

  it("prefers Telegram when several bridges are available", () => {
    expect(
      detectLaunch({
        telegramInitData: TELEGRAM_RAW,
        maxInitData: MAX_RAW,
        search: "?vk_user_id=42&sign=abc",
      }),
    ).toEqual({ platform: "telegram", payload: TELEGRAM_RAW });
  });
});

describe("readMaxFragmentPayload", () => {
  it("returns null without the WebAppData marker", () => {
    expect(readMaxFragmentPayload("#other=1")).toBeNull();
    expect(readMaxFragmentPayload(null)).toBeNull();
  });
});

describe("initializePlatform", () => {
  it("announces a Telegram mini app", () => {
    const ready = vi.fn();
    const expand = vi.fn();

    initializePlatform("telegram", { telegram: { ready, expand } });

    expect(ready).toHaveBeenCalledTimes(1);
    expect(expand).toHaveBeenCalledTimes(1);
  });

  it("sends VKWebAppInit once", () => {
    const sendVkInit = vi.fn();

    initializePlatform("vk", { sendVkInit });
    initializePlatform("vk", { sendVkInit });

    expect(sendVkInit).toHaveBeenCalledTimes(1);
  });

  it("leaves plain web pages alone", () => {
    const sendVkInit = vi.fn();
    const ready = vi.fn();

    initializePlatform("web", { sendVkInit, telegram: { ready } });

    expect(sendVkInit).not.toHaveBeenCalled();
    expect(ready).not.toHaveBeenCalled();
  });
});
