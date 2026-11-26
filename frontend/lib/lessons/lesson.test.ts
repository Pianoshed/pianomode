import { describe, expect, it } from "vitest";
import list from "./__fixtures__/lesson-list.json";
import triads from "./__fixtures__/lesson-triads.json";
import type { Example, LessonDetail, LessonList, LessonSummary } from "./api";
import {
  centreOfItem,
  eventsFor,
  exampleBeats,
  goalText,
  groupByLevel,
  itemAtBeat,
  overlayForItem,
  practiceHref,
  suggestNext,
  summaryCounts,
} from "./lesson";

// Contract check: if the API response drifts from the hand-written types, `npm run typecheck` fails.
const lessons: LessonList = list as LessonList;
const lesson: LessonDetail = triads as LessonDetail;
const ex = (i: number, s = 0): Example => lesson.sections[s]!.examples[i]!;
const summary = (over: Partial<LessonSummary>): LessonSummary => ({
  id: "x", title: "X", level: "beginner", summary: "", tags: [], prerequisites: [], unmet_prerequisites: [],
  status: "not_started", goals_met: 0, goals_total: 1, ...over,
});

describe("contract with the API", () => {
  it("lists the curriculum, untouched at first", () => {
    expect(lessons.items.length).toBeGreaterThanOrEqual(12);
    expect(lessons.items[0]!.unmet_prerequisites).toEqual([]);
    expect(lessons.items.every((i) => i.status === "not_started")).toBe(true);
  });
  it("a lesson carries engine-built examples and practice progress", () => {
    expect(ex(0).items[0]!.notes).toEqual(["C", "E", "G"]);
    expect(ex(0).items[0]!.midi).toEqual([60, 64, 67]);
    expect(lesson.practice[0]).toMatchObject({ kind: "triad_build", correct: 3, goal: 3, met: true });
    expect(lesson.status).toBe("in_progress");
  });
});

describe("wording and links", () => {
  it("goalText never exceeds the goal", () => {
    expect(goalText({ correct: 2, goal: 5 })).toBe("2 of 5");
    expect(goalText({ correct: 9, goal: 5 })).toBe("5 of 5");
  });
  it("practiceHref opens the theory screen on that exercise and level", () => {
    expect(practiceHref({ kind: "triad_build", difficulty: "beginner" })).toBe("/theory?kind=triad_build&level=beginner");
  });
});

describe("ordering", () => {
  it("groups by level in curriculum order and omits empty levels", () => {
    const g = groupByLevel([summary({ id: "a", level: "advanced" }), summary({ id: "b", level: "beginner" }), summary({ id: "c", level: "advanced" })]);
    expect(g.map((x) => x.level)).toEqual(["beginner", "advanced"]);
    expect(g[1]!.lessons.map((l) => l.id)).toEqual(["a", "c"]);
  });
  it("suggests the first unfinished lesson that is ready", () => {
    const items = [
      summary({ id: "a", status: "practised" }),
      summary({ id: "b", unmet_prerequisites: ["z"] }),
      summary({ id: "c", status: "in_progress" }),
    ];
    expect(suggestNext(items)!.id).toBe("c");
  });
  it("falls back to the first unfinished one, and to null when all are practised", () => {
    expect(suggestNext([summary({ id: "a", unmet_prerequisites: ["z"] })])!.id).toBe("a");
    expect(suggestNext([summary({ status: "practised" })])).toBeNull();
    expect(suggestNext([])).toBeNull();
  });
  it("counts practised lessons", () => {
    expect(summaryCounts([summary({ status: "practised" }), summary({})])).toEqual({ practised: 1, total: 2 });
  });
});

describe("overlayForItem", () => {
  it("marks every note of a chord, the root distinctly, with spelled names", () => {
    const o = overlayForItem(ex(1), 0)!; // C minor
    expect([...o.marks.keys()]).toEqual(ex(1).items[0]!.midi);
    expect([...o.marks.values()].map((m) => m.role)).toEqual(["root", "tone", "tone"]);
    expect([...o.marks.values()].map((m) => m.label)).toEqual(["C", "Eb", "G"]);
    expect(o.title).toBe("Cm");
  });
  it("a scale marks the current note, with the tonic as root", () => {
    const scale: Example = { type: "scale", caption: "", tempo: 120, play: [], items: [
      { label: "C", notes: ["C"], midi: [60], detail: "degree 1" },
      { label: "D", notes: ["D"], midi: [62], detail: "degree 2" },
    ] };
    expect(overlayForItem(scale, 0)!.marks.get(60)!.role).toBe("root");
    expect(overlayForItem(scale, 1)!.marks.get(62)!.role).toBe("tone");
  });
  it("an interval marks both notes as tones", () => {
    const iv: Example = { type: "interval", caption: "", tempo: 80, play: [], items: [{ label: "M3", notes: ["C", "E"], midi: [60, 64], detail: "M3" }] };
    expect([...overlayForItem(iv, 0)!.marks.values()].map((m) => m.role)).toEqual(["tone", "tone"]);
  });
  it("a slash chord marks the chord's root, not its bass", () => {
    const slash: Example = { type: "sequence", caption: "", tempo: 72, play: [], items: [{ label: "C/E", notes: ["E", "G", "C"], midi: [64, 67, 72], detail: "I6" }] };
    const roles = [...overlayForItem(slash, 0)!.marks.entries()].map(([m, k]) => [m % 12, k.role]);
    expect(roles).toEqual([[4, "tone"], [7, "tone"], [0, "root"]]);
  });
  it("returns nothing for a missing item", () => {
    expect(overlayForItem(ex(0), 5)).toBeNull();
  });
});

describe("playback helpers", () => {
  const seq: Example = { type: "sequence", caption: "", tempo: 72, items: [], play: [
    { notes: [60], start: 0, duration: 2, item: 0 }, { notes: [62], start: 2, duration: 2, item: 1 }, { notes: [64], start: 4, duration: 2, item: 2 },
  ] };
  it("converts steps to scheduled events", () => {
    expect(eventsFor(seq)).toEqual([{ notes: [60], start: 0, duration: 2 }, { notes: [62], start: 2, duration: 2 }, { notes: [64], start: 4, duration: 2 }]);
  });
  it("finds the sounding item at a beat", () => {
    expect([0, 1.99, 2, 3.5, 4, 99].map((b) => itemAtBeat(seq, b))).toEqual([0, 0, 1, 1, 2, 2]);
    expect(itemAtBeat({ play: [] }, 3)).toBe(0);
  });
  it("totals the length", () => {
    expect(exampleBeats(seq)).toBe(6);
    expect(exampleBeats({ play: [] })).toBe(0);
  });
  it("centres on the middle of an item", () => {
    expect(centreOfItem({ midi: [60, 64, 67] })).toBe(64);
    expect(centreOfItem({ midi: [] })).toBeNull();
  });
});
