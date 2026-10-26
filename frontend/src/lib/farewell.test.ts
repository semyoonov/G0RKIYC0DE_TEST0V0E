import { describe, expect, it } from "vitest";

import { farewellWords, isFarewellUtterance } from "./farewell";

describe("isFarewellUtterance", () => {
  it.each([
    "Спасибо",
    "спасибо большое",
    "Спс!",
    "До свидания",
    "до свидания, спасибо",
    "Пока",
    "ПОКА!",
    "ну всё, хватит",
    "На этом всё",
    "на этом всё, спасибо",
    "До-свидания",
  ])("treats %s as a closing utterance", (text) => {
    expect(isFarewellUtterance(text)).toBe(true);
  });

  it.each([
    "",
    "   ",
    "Покажи задачи на сегодня",
    "Спасибо за подробный ответ, это очень полезно",
    "на этом этапе всё хорошо",
    "на этом",
    "этом всё на",
    "на этом всё спасибо вам",
  ])("does not treat %s as a closing utterance", (text) => {
    expect(isFarewellUtterance(text)).toBe(false);
  });

  it("counts at most four words", () => {
    expect(isFarewellUtterance("на этом всё спасибо")).toBe(true);
    expect(isFarewellUtterance("на этом всё спасибо вам")).toBe(false);
  });

  it("normalizes case, punctuation and ё", () => {
    expect(farewellWords("  До свидания, Спасибо!  ")).toEqual(["до", "свидания", "спасибо"]);
    expect(isFarewellUtterance("НА ЭТОМ ВСЁ")).toBe(true);
  });

  it("does not match a farewell word inside another word", () => {
    expect(isFarewellUtterance("показать")).toBe(false);
    expect(isFarewellUtterance("спасибочки")).toBe(false);
  });

  it("accepts the added closing phrases", () => {
    for (const phrase of [
      "благодарю",
      "до связи",
      "всего доброго",
      "всё на этом",
      "закончили",
      "отбой",
      "до встречи",
    ]) {
      expect(isFarewellUtterance(phrase)).toBe(true);
    }
  });
});
