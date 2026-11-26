import { describe, expect, it } from "vitest";
import { MAX_RECORDED, Recorder, reportedLatencyMs } from "./recorder";
import { askedSteps, pressNote, startWait } from "./wait";

describe("wait mode", () => {
  const plan = [[60, 64, 67], [62, 65, 69]];

  it("asks for each chord in turn and counts a clean chord as first time", () => {
    let w = startWait(plan);
    for (const n of [60, 64]) w = pressNote(w, plan, n);
    expect(w).toMatchObject({ index: 0, got: [60, 64] });
    w = pressNote(w, plan, 67);
    expect(w).toMatchObject({ index: 1, got: [], firstTry: 1, wrongNow: 0, done: false });
    for (const n of [69, 62, 65]) w = pressNote(w, plan, n); // any order
    expect(w).toMatchObject({ done: true, firstTry: 2, wrongTotal: 0 });
  });

  it("counts wrong notes and does not count that chord as first time", () => {
    let w = startWait(plan);
    w = pressNote(w, plan, 61);
    w = pressNote(w, plan, 62);
    expect(w).toMatchObject({ wrongNow: 2, wrongTotal: 2, got: [] });
    for (const n of [60, 64, 67]) w = pressNote(w, plan, n);
    expect(w).toMatchObject({ index: 1, firstTry: 0, wrongNow: 0, wrongTotal: 2 });
  });

  it("does not punish a repeated wanted note", () => {
    let w = startWait(plan);
    w = pressNote(pressNote(w, plan, 60), plan, 60);
    expect(w).toMatchObject({ got: [60], wrongNow: 0 });
  });

  it("can accept any octave", () => {
    let w = startWait([[60]]);
    expect(pressNote(w, [[60]], 72).done).toBe(false);
    w = pressNote(w, [[60]], 72, true);
    expect(w).toMatchObject({ done: true, firstTry: 1 });
  });

  it("skips chords that ask nothing of the chosen hand", () => {
    const p = [[], [60], [], [62], []];
    let w = startWait(p);
    expect(w.index).toBe(1);
    w = pressNote(w, p, 60);
    expect(w.index).toBe(3);
    w = pressNote(w, p, 62);
    expect(w.done).toBe(true);
    expect(askedSteps(p)).toBe(2);
  });

  it("ignores presses once finished and handles an empty plan", () => {
    const w = pressNote(startWait([[60]]), [[60]], 60);
    expect(pressNote(w, [[60]], 99)).toBe(w);
    expect(startWait([]).done).toBe(true);
    expect(startWait([[], []]).done).toBe(true);
  });
});

describe("recorder", () => {
  it("pairs releases with presses and keeps time order", () => {
    const r = new Recorder();
    r.noteOn(64, 1.0);
    r.noteOn(60, 0.5);
    r.noteOff(60, 0.9);
    expect(r.notes()).toEqual([{ midi: 60, time_s: 0.5, off_time_s: 0.9 }, { midi: 64, time_s: 1.0 }]);
  });

  it("keeps both presses when a key is pressed twice without a release", () => {
    const r = new Recorder();
    r.noteOn(60, 1);
    r.noteOn(60, 2);
    expect(r.notes().map((n) => n.time_s)).toEqual([1, 2]);
  });

  it("ignores a release with no press, a negative time and a release before the press", () => {
    const r = new Recorder();
    r.noteOff(60, 1);
    r.noteOn(60, -1);
    expect(r.notes()).toEqual([]);
    r.noteOn(62, 2);
    r.noteOff(62, 1);
    expect(r.notes()).toEqual([{ midi: 62, time_s: 2 }]);
  });

  it("selects the notes in a time range and clears", () => {
    const r = new Recorder();
    for (const t of [1, 2, 3, 4]) r.noteOn(60 + t, t);
    expect(r.between(1.5, 3).map((n) => n.time_s)).toEqual([2, 3]);
    r.clear();
    expect(r.notes()).toEqual([]);
  });

  it("stops recording at the limit", () => {
    const r = new Recorder();
    for (let i = 0; i < MAX_RECORDED + 10; i++) {
      r.noteOn(60, i);
      r.noteOff(60, i + 0.1);
    }
    expect(r.notes()).toHaveLength(MAX_RECORDED);
  });

  it("reports the browser's sound delay within bounds", () => {
    expect(reportedLatencyMs(null)).toBe(0);
    expect(reportedLatencyMs({})).toBe(0);
    expect(reportedLatencyMs({ outputLatency: 0.045 })).toBe(45);
    expect(reportedLatencyMs({ outputLatency: 0, baseLatency: 0.01 })).toBe(10);
    expect(reportedLatencyMs({ outputLatency: 9 })).toBe(500);
  });
});
