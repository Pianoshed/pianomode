import { describe, expect, it } from "vitest";
import { parseThemeChoice, resolveTheme } from "@/lib/theme";

describe("theme", () => {
  it("falls back to system for missing or unknown stored values", () => {
    expect(parseThemeChoice(null)).toBe("system");
    expect(parseThemeChoice("purple")).toBe("system");
    expect(parseThemeChoice("dark")).toBe("dark");
    expect(parseThemeChoice("light")).toBe("light");
  });

  it("resolves system from the OS preference and honours explicit choices", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});
