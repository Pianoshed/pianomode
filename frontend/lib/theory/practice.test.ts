import { describe, expect, it } from "vitest";
import exerciseKinds from "../piano/__fixtures__/exercise-kinds.json";
import exerciseGrade from "../piano/__fixtures__/exercise-grade.json";
import exerciseSet from "../piano/__fixtures__/exercise-set.json";
import type { Exercise, ExerciseKind, Grade, KindList, KindProgress } from "./exercisesApi";
import { randomSeed } from "./exercisesApi";
import {
  EMPTY_DRAFT,
  answerFor,
  describeProgress,
  groupByTopic,
  overlayForExercise,
  progressFor,
  splitList,
  toggleKey,
  topicLabel,
  untriedPrerequisites,
} from "./practice";

const draft = (over: Partial<typeof EMPTY_DRAFT>) => ({ ...EMPTY_DRAFT, ...over });
const kind = (k: string, topic: string, prerequisites: string[] = []): ExerciseKind => ({
  kind: k, title: k.toUpperCase(), topic, objective: "", prerequisites, ear_training: false,
});
const prog = (over: Partial<KindProgress>): KindProgress => ({
  kind: "a", difficulty: "beginner", attempts: 0, correct: 0, recent_attempts: 0, recent_correct: 0, last_at: "", ...over,
});

describe("answerFor", () => {
  it("choice sends the chosen option, nothing until one is chosen", () => {
    expect(answerFor("choice", EMPTY_DRAFT)).toBeNull();
    expect(answerFor("choice", draft({ choice: "M3" }))).toBe("M3");
  });
  it("text is trimmed and empty means unanswered", () => {
    expect(answerFor("text", draft({ text: "  Dm7/C " }))).toBe("Dm7/C");
    expect(answerFor("text", draft({ text: "   " }))).toBeNull();
  });
  it("note_names and chord_symbols split on spaces and commas", () => {
    expect(answerFor("note_names", draft({ text: "C D, E  F#" }))).toEqual(["C", "D", "E", "F#"]);
    expect(answerFor("chord_symbols", draft({ text: "Am, Dm  E7" }))).toEqual(["Am", "Dm", "E7"]);
    expect(answerFor("note_names", draft({ text: " , " }))).toBeNull();
  });
  it("note_set prefers pressed keys, sorted, and falls back to typed names", () => {
    expect(answerFor("note_set", draft({ keys: new Set([67, 60, 64]), text: "C E G" }))).toEqual([60, 64, 67]);
    expect(answerFor("note_set", draft({ text: "F# A C#" }))).toEqual(["F#", "A", "C#"]);
    expect(answerFor("note_set", EMPTY_DRAFT)).toBeNull();
  });
});

describe("keyboard helpers", () => {
  const ex = { show: [60, 64] } as Exercise;
  it("never labels the keys, so the answer is not given away", () => {
    const o = overlayForExercise(ex, new Set())!;
    expect([...o.marks.values()].every((m) => m.label === "")).toBe(true);
    expect([...o.marks.keys()]).toEqual([60, 64]);
  });
  it("shows picked keys distinctly and returns nothing when there is nothing to show", () => {
    const o = overlayForExercise({ show: [] } as unknown as Exercise, new Set([62]))!;
    expect(o.marks.get(62)!.role).toBe("root");
    expect(overlayForExercise({ show: [] } as unknown as Exercise, new Set())).toBeNull();
    expect(overlayForExercise(null, new Set())).toBeNull();
  });
  it("toggleKey adds, removes and does not mutate", () => {
    const a = new Set([60]);
    const b = toggleKey(a, 64);
    expect([...b].sort()).toEqual([60, 64]);
    expect([...a]).toEqual([60]);
    expect([...toggleKey(b, 60)]).toEqual([64]);
  });
});

describe("grouping and progress", () => {
  it("groups by topic in server order", () => {
    const g = groupByTopic([kind("a", "Notes"), kind("b", "Chords"), kind("c", "Notes")]);
    expect(g.map((x) => x.topic)).toEqual(["Notes", "Chords"]);
    expect(g[0]!.kinds.map((k) => k.kind)).toEqual(["a", "c"]);
  });
  it("describes progress as plain counts", () => {
    expect(describeProgress(undefined).summary).toBe("Not tried yet");
    expect(describeProgress(prog({ attempts: 4, correct: 3, recent_attempts: 4, recent_correct: 3 }))).toEqual({
      summary: "3 of 4 correct", recent: null,
    });
    expect(describeProgress(prog({ attempts: 30, correct: 20, recent_attempts: 10, recent_correct: 9 })).recent).toBe("9 of your last 10");
  });
  it("finds progress by kind and difficulty", () => {
    const rows = [prog({ kind: "a", difficulty: "beginner", attempts: 1 }), prog({ kind: "a", difficulty: "expert", attempts: 2 })];
    expect(progressFor(rows, "a", "expert")!.attempts).toBe(2);
    expect(progressFor(rows, "a", "advanced")).toBeUndefined();
  });
  it("lists prerequisites not yet tried, by title", () => {
    const all = [kind("a", "T"), kind("b", "T"), kind("c", "T", ["a", "b"])];
    expect(untriedPrerequisites(all[2]!, all, [prog({ kind: "a", attempts: 2 })])).toEqual(["B"]);
    expect(untriedPrerequisites(all[2]!, all, [prog({ kind: "a", attempts: 0 })])).toEqual(["A", "B"]);
    expect(untriedPrerequisites(all[0]!, all, [])).toEqual([]);
  });
});

describe("misc", () => {
  it("topicLabel turns identifiers into words", () => {
    expect(topicLabel("seventh_chords")).toBe("Seventh chords");
    expect(topicLabel("notes")).toBe("Notes");
    expect(topicLabel("")).toBe("");
  });
  it("splitList", () => expect(splitList("a,b  c")).toEqual(["a", "b", "c"]));
  it("randomSeed stays inside what the server accepts", () => {
    expect(randomSeed(() => 0)).toBe(0);
    expect(randomSeed(() => 0.999999999)).toBeLessThan(2 ** 31);
    expect(Number.isInteger(randomSeed())).toBe(true);
  });
});

// Contract check: if the API response drifts from the hand-written types, `npm run typecheck` fails.
describe("contract with the API", () => {
  const kinds: KindList = exerciseKinds as KindList;
  const ex: Exercise = (exerciseSet as { exercises: Exercise[] }).exercises[0]!;
  const grade: Grade = exerciseGrade as Grade;
  it("lists the kinds and difficulties", () => {
    expect(kinds.kinds.length).toBeGreaterThan(20);
    expect(kinds.difficulties).toEqual(["beginner", "intermediate", "advanced", "expert"]);
  });
  it("an exercise carries what the screen needs", () => {
    expect(ex.id).toMatch(/^v\d+:triad_identify:beginner:3$/);
    expect(ex.answer_format).toBe("text");
    expect(ex.show.length).toBeGreaterThan(0);
  });
  it("an unreadable answer is graded as unreadable, not as wrong", () => {
    expect(grade.status).toBe("unreadable");
    expect(answerFor(ex.answer_format, draft({ text: "Zm" }))).toBe("Zm");
  });
});
