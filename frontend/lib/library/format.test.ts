import { describe, expect, it } from "vitest";
import { formatBytes, percentUsed, relativeDay, studioHref } from "@/lib/library/format";

describe("library formatting", () => {
  it("formats sizes", () => {
    expect([formatBytes(0), formatBytes(900), formatBytes(1536), formatBytes(50_000), formatBytes(5 * 1024 * 1024)]).toEqual(["0 B", "900 B", "1.5 KB", "49 KB", "5.0 MB"]);
  });
  it("caps the usage bar", () => {
    expect([percentUsed(50, 200), percentUsed(500, 200), percentUsed(1, 0)]).toEqual([25, 100, 0]);
  });
  it("says how long ago in plain words", () => {
    const now = new Date(2026, 10, 14, 15, 0);
    expect(relativeDay(new Date(2026, 10, 14, 1, 0).toISOString(), now)).toBe("Today");
    expect(relativeDay(new Date(2026, 10, 13, 23, 0).toISOString(), now)).toBe("Yesterday");
    expect(relativeDay(new Date(2026, 10, 11, 9, 0).toISOString(), now)).toBe("3 days ago");
    expect(relativeDay(new Date(2026, 9, 1, 9, 0).toISOString(), now)).toBe("1 Oct 2026");
  });
  it("builds studio links that survive odd ids", () => {
    expect(studioHref("midi", "abc-123")).toBe("/midi?project=abc-123");
  });
});
