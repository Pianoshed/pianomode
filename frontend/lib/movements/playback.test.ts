import { describe, expect, it } from "vitest";
import detail from "./__fixtures__/movement-ii-v-i.json";
import {
  BOTH_HANDS,
  beatSeconds,
  centreMidi,
  eventsFrom,
  overlayFromStep,
  resumeBeat,
  stepAtBeat,
  stepEvent,
} from "./playback";
import { type MovementDetail, transitionLabel } from "./api";

// Contract check: if the API response drifts from the hand-written types, `npm run typecheck` fails.
const fixture: MovementDetail = detail as MovementDetail;
const version = (level: string) => fixture.movement.versions.find((v) => v.level === level)!;
const inter = version("intermediate");

describe("contract with the API", () => {
  it("has the four levels in order", () => {
    expect(fixture.movement.versions.map((v) => v.level)).toEqual(["beginner", "intermediate", "advanced", "expert"]);
  });
  it("intermediate ii-V-I is Dm7 G7 Cmaj7, expert substitutes the tritone", () => {
    expect(inter.steps.map((s) => s.symbol)).toEqual(["Dm7", "G7", "Cmaj7"]);
    expect(version("expert").steps.map((s) => s.symbol)).toEqual(["Dm7", "Db7", "Cmaj7"]);
  });
});

describe("stepAtBeat", () => {
  it("finds the chord at a beat and on boundaries", () => {
    expect(stepAtBeat(inter, 0)).toBe(0);
    expect(stepAtBeat(inter, 3.99)).toBe(0);
    expect(stepAtBeat(inter, 4)).toBe(1);
    expect(stepAtBeat(inter, 8)).toBe(2);
  });
  it("clamps before the start and after the end", () => {
    expect(stepAtBeat(inter, -3)).toBe(0);
    expect(stepAtBeat(inter, 999)).toBe(2);
  });
  it("copes with no chords", () => {
    expect(stepAtBeat({ steps: [] }, 1)).toBe(-1);
  });
});

describe("eventsFrom", () => {
  it("from the top, every note of every chord appears once", () => {
    const events = eventsFrom(inter, 0, BOTH_HANDS);
    const total = inter.steps.reduce((n, s) => n + s.left.length + s.right.length, 0);
    expect(events.reduce((n, e) => n + e.notes.length, 0)).toBe(total);
    expect(events.map((e) => e.start)).toEqual([...events.map((e) => e.start)].sort((a, b) => a - b));
  });
  it("hand muting removes only that hand", () => {
    const rightOnly = eventsFrom(inter, 0, { L: false, R: true }).flatMap((e) => e.notes);
    const expected = inter.steps.flatMap((s) => s.right);
    expect(rightOnly.sort()).toEqual(expected.sort());
    expect(eventsFrom(inter, 0, { L: false, R: false })).toEqual([]);
  });
  it("starting mid-way drops finished chords and re-times the rest", () => {
    const events = eventsFrom(inter, 4, BOTH_HANDS);
    const second = inter.steps[1]!;
    const first = events[0]!;
    expect(first.start).toBe(0);
    expect([...first.notes].sort()).toEqual([...second.left, ...second.right].sort());
    expect(events.at(-1)!.start).toBe(4);
  });
  it("a note already sounding keeps only its remaining length", () => {
    const events = eventsFrom(inter, 2, BOTH_HANDS);
    expect(events[0]!.start).toBe(0);
    expect(events[0]!.duration).toBe(2);
  });
  it("after the end there is nothing to play", () => {
    expect(eventsFrom(inter, inter.total_beats, BOTH_HANDS)).toEqual([]);
  });
});

describe("stepEvent", () => {
  it("auditions a chord with the unmuted hands and gives nothing if both are muted", () => {
    const s = inter.steps[0]!;
    expect(stepEvent(s, BOTH_HANDS)[0]!.notes.length).toBe(s.left.length + s.right.length);
    expect(stepEvent(s, { L: false, R: false })).toEqual([]);
  });
});

describe("overlayFromStep", () => {
  const g7 = inter.steps[1]!;
  it("marks every sounding key with its hand and spelled name", () => {
    const o = overlayFromStep(g7, BOTH_HANDS);
    expect([...o.marks.keys()].sort((a, b) => a - b)).toEqual([...g7.left, ...g7.right].sort((a, b) => a - b));
    for (const m of g7.left) expect(o.marks.get(m)!.hand).toBe("L");
    for (const m of g7.right) expect(o.marks.get(m)!.hand).toBe("R");
    expect(o.title).toBe("G7 (V7)");
  });
  it("marks roots, and exactly one lowest note as the bass", () => {
    const o = overlayFromStep(g7, BOTH_HANDS);
    const roots = [...o.marks.entries()].filter(([, m]) => m.role === "root").map(([k]) => k % 12);
    expect(roots.every((pc) => pc === 7)).toBe(true);
    const bass = [...o.marks.entries()].filter(([, m]) => m.bass).map(([k]) => k);
    expect(bass).toEqual([Math.min(...g7.left, ...g7.right)]);
  });
  it("a muted hand shows no marks and the bass follows the hand still sounding", () => {
    const o = overlayFromStep(g7, { L: false, R: true });
    expect([...o.marks.keys()].sort()).toEqual([...g7.right].sort());
    expect([...o.marks.values()].filter((m) => m.bass).length).toBe(1);
  });
  it("spelling follows the chord, not a sharps/flats guess", () => {
    const db7 = version("expert").steps[1]!;
    const o = overlayFromStep(db7, BOTH_HANDS);
    expect(o.spelling[1]).toBe("Db");
  });
});

describe("small helpers", () => {
  it("centreMidi is the middle of the chord's range", () => {
    expect(centreMidi({ ...inter.steps[0]!, left: [48], right: [60, 72] })).toBe(60);
    expect(centreMidi({ ...inter.steps[0]!, left: [], right: [] })).toBeNull();
  });
  it("resumeBeat stays inside the music", () => {
    expect(resumeBeat(5, { total_beats: 12 })).toBe(5);
    expect(resumeBeat(50, { total_beats: 12 })).toBeLessThan(12);
    expect(resumeBeat(-2, { total_beats: 12 })).toBe(0);
    expect(resumeBeat(3, { total_beats: 0 })).toBe(0);
  });
  it("beatSeconds clamps the tempo", () => {
    expect(beatSeconds(60)).toBe(1);
    expect(beatSeconds(1)).toBe(3);
    expect(beatSeconds(9999)).toBeCloseTo(0.15);
  });
  it("transition buttons are named for what they do", () => {
    expect(transitionLabel("published", "approved")).toBe("Unpublish");
    expect(transitionLabel("archived", "draft")).toBe("Restore");
    expect(transitionLabel("approved", "published")).toBe("Publish");
    expect(transitionLabel("draft", "under_review")).toBe("Submit for review");
  });
});
