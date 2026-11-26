import { describe, expect, it } from "vitest";
import { definitionFromForm, emptyForm, formFromDefinition, lessonTransitionLabel, paragraphs, words } from "./admin";

describe("lesson authoring helpers", () => {
  it("splits paragraphs on blank lines and words on spaces, commas and semicolons", () => {
    expect(paragraphs("One.\nStill one.\n\nTwo.\n \n\nThree.")).toEqual(["One.\nStill one.", "Two.", "Three."]);
    expect(words("a b, c;d  ")).toEqual(["a", "b", "c", "d"]);
  });

  it("builds a definition from the form, parsing octaves and chord lists", () => {
    const f = emptyForm();
    f.id = " ii-v-i-demo ";
    f.title = "Demo ";
    f.summary = " s ";
    f.objectives = "First.\n\n Second.\n";
    f.prerequisites = "triads, inversions";
    f.sections = [
      {
        heading: "H",
        body: "P1\n\nP2",
        examples: [
          { type: "sequence", caption: "c", fields: { chords: "Dm7 G7 Cmaj7", key: "C major", octave: "4" } },
          { type: "interval", caption: "i", fields: { lower: "C4", upper: "G4", octave: "ignored" } },
        ],
      },
    ];
    f.practice = [{ kind: "interval_identify", difficulty: "beginner", goal: "5" }];
    const d = definitionFromForm(f);
    expect(d.id).toBe("ii-v-i-demo");
    expect(d.objectives).toEqual(["First.", "Second."]);
    expect(d.prerequisites).toEqual(["triads", "inversions"]);
    expect(d.sections[0]!.body).toEqual(["P1", "P2"]);
    expect(d.sections[0]!.examples[0]).toEqual({ type: "sequence", caption: "c", chords: ["Dm7", "G7", "Cmaj7"], key: "C major", octave: 4 });
    expect(d.sections[0]!.examples[1]).toEqual({ type: "interval", caption: "i", lower: "C4", upper: "G4" });
    expect(d.practice).toEqual([{ kind: "interval_identify", difficulty: "beginner", goal: 5 }]);
    expect(d.movement_template).toBeNull();
  });

  it("passes a non-numeric octave through so the engine can refuse it", () => {
    const f = emptyForm();
    f.sections[0]!.examples = [{ type: "chord", caption: "c", fields: { symbol: "C", octave: "four" } }];
    expect(definitionFromForm(f).sections[0]!.examples[0]!.octave).toBe("four");
  });

  it("round-trips a stored definition through the form", () => {
    const stored = {
      id: "x-y", title: "T", level: "advanced" as const, summary: "S", objectives: ["a", "b"], prerequisites: ["p"],
      sections: [{ heading: "H", body: ["one", "two"], examples: [{ type: "sequence" as const, caption: "c", chords: ["C", "G"], key: "C major", octave: 3 }] }],
      practice: [{ kind: "note_name", difficulty: "beginner" as const, goal: 4 }], movement_template: "ii_v_i", tags: ["t"],
    };
    expect(definitionFromForm(formFromDefinition(stored))).toEqual(stored);
  });

  it("falls back to a usable blank form", () => {
    const f = formFromDefinition({});
    expect(f.sections).toHaveLength(1);
    expect(f.practice).toHaveLength(1);
  });

  it("labels status changes", () => {
    expect(lessonTransitionLabel("draft", "under_review")).toBe("Submit for review");
    expect(lessonTransitionLabel("published", "approved")).toBe("Unpublish");
    expect(lessonTransitionLabel("published", "archived")).toBe("Archive");
    expect(lessonTransitionLabel("archived", "draft")).toBe("Restore");
  });
});
