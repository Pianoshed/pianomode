import { describe, expect, it } from "vitest";
import { definitionFromForm, scaleTransitionLabel, splitAliases, splitTokens } from "./api";

describe("scale admin helpers", () => {
  it("splits interval formulas on spaces and commas", () => {
    expect(splitTokens("P1 M2, m3  A4;P5")).toEqual(["P1", "M2", "m3", "A4", "P5"]);
    expect(splitTokens("  ")).toEqual([]);
  });

  it("turns aliases into the identifier form the API accepts", () => {
    expect(splitAliases("Gypsy minor, Double-harmonic")).toEqual(["gypsy_minor", "double_harmonic"]);
  });

  it("builds a definition, leaving the descending form null when empty", () => {
    const d = definitionFromForm({
      id: " hungarian_minor ", name: "Hungarian minor ", family: "", formula: "P1 M2 m3 A4 P5 m6 M7",
      descending: "", aliases: "gypsy minor", description: " ",
    });
    expect(d).toEqual({
      id: "hungarian_minor", name: "Hungarian minor", family: "custom",
      formula: ["P1", "M2", "m3", "A4", "P5", "m6", "M7"], descending: null,
      aliases: ["gypsy_minor"], description: "",
    });
  });

  it("labels status changes for buttons", () => {
    expect(scaleTransitionLabel("draft", "published")).toBe("Publish");
    expect(scaleTransitionLabel("published", "draft")).toBe("Unpublish");
    expect(scaleTransitionLabel("archived", "draft")).toBe("Restore");
  });
});
