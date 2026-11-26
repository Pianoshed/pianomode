import { describe, expect, it } from "vitest";
import {
  MAX_PASSES,
  type PracticePlan,
  allClicks,
  clampTempo,
  clicksForPass,
  defaultPlan,
  effectiveTempo,
  loopFromSteps,
  loopProblem,
  notesForPass,
  passPercent,
  passTempo,
  passTiming,
  planProblems,
  planSeconds,
  positionAt,
  scoringParams,
  snapLoopToBars,
  timeAtBeat,
  timeline,
} from "./clock";

// 120 BPM: one beat is exactly half a second, which keeps every expected number easy to check.
const PIECE = { tempo: 120, time_signature: [4, 4], total_beats: 16 };
const plan = (o: Partial<PracticePlan> = {}): PracticePlan => defaultPlan(PIECE, o);
const near = (a: number, b: number) => expect(a).toBeCloseTo(b, 9);

describe("tempo", () => {
  it("scales and clamps", () => {
    expect(effectiveTempo(120, 50)).toBe(60);
    expect(effectiveTempo(120, 200)).toBe(240);
    expect(effectiveTempo(300, 200)).toBe(400);
    expect(effectiveTempo(30, 10)).toBe(20);
    expect(effectiveTempo(100, 5)).toBe(20); // 5% is raised to 10%, which is 10 BPM, then to the 20 BPM floor
    expect(effectiveTempo(100, 1000)).toBe(200); // percent is capped at 200
    expect(clampTempo(5)).toBe(20);
    expect(clampTempo(999)).toBe(400);
  });

  it("takes bar length and count-in from the time signature", () => {
    const p = defaultPlan({ tempo: 90, time_signature: [3, 4], total_beats: 12 });
    expect(p.beatsPerBar).toBe(3);
    expect(p.countInBeats).toBe(3);
    expect(p.percent).toBe(100);
    expect(p.loop).toBeNull();
  });
});

describe("loops", () => {
  it("rejects loops that cannot be played", () => {
    expect(loopProblem({ startBeat: 0, endBeat: 16 }, 16)).toBeNull();
    expect(loopProblem({ startBeat: 4, endBeat: 8 }, 16)).toBeNull();
    expect(loopProblem({ startBeat: -1, endBeat: 4 }, 16)).toMatch(/before the piece/);
    expect(loopProblem({ startBeat: 4, endBeat: 17 }, 16)).toMatch(/after the piece/);
    expect(loopProblem({ startBeat: 4, endBeat: 4.5 }, 16)).toMatch(/one beat/);
    expect(loopProblem({ startBeat: 8, endBeat: 4 }, 16)).toMatch(/one beat/);
    expect(loopProblem({ startBeat: Number.NaN, endBeat: 4 }, 16)).toMatch(/start and an end/);
  });

  it("snaps outward to whole bars and stays inside the piece", () => {
    expect(snapLoopToBars({ startBeat: 5, endBeat: 10 }, 4, 16)).toEqual({ startBeat: 4, endBeat: 12 });
    expect(snapLoopToBars({ startBeat: 4, endBeat: 8 }, 4, 16)).toEqual({ startBeat: 4, endBeat: 8 });
    expect(snapLoopToBars({ startBeat: 13, endBeat: 15 }, 4, 16)).toEqual({ startBeat: 12, endBeat: 16 });
    expect(snapLoopToBars({ startBeat: 0.5, endBeat: 4.2 }, 4, 16)).toEqual({ startBeat: 0, endBeat: 8 });
    expect(snapLoopToBars({ startBeat: 13, endBeat: 15 }, 4, 14)).toEqual({ startBeat: 12, endBeat: 14 });
  });

  it("builds a loop from a range of chords, in either order", () => {
    const steps = [
      { beat: 0, duration: 4 },
      { beat: 4, duration: 4 },
      { beat: 8, duration: 4 },
    ];
    expect(loopFromSteps(steps, 1, 1, 12)).toEqual({ startBeat: 4, endBeat: 8 });
    expect(loopFromSteps(steps, 2, 1, 12)).toEqual({ startBeat: 4, endBeat: 12 });
    expect(loopFromSteps(steps, -3, 99, 12)).toEqual({ startBeat: 0, endBeat: 12 });
    expect(loopFromSteps([], 0, 1, 12)).toBeNull();
  });
});

describe("plan checks", () => {
  it("accepts a normal plan and names each problem", () => {
    expect(planProblems(plan())).toEqual([]);
    expect(planProblems(plan({ baseTempo: 5 }))).toHaveLength(1);
    expect(planProblems(plan({ beatsPerBar: 0 }))).toHaveLength(1);
    expect(planProblems(plan({ countInBeats: 20 }))).toHaveLength(1);
    expect(planProblems(plan({ totalBeats: 0 }))).toHaveLength(1);
    expect(planProblems(plan({ percent: 500 }))).toHaveLength(1);
    expect(planProblems(plan({ loop: { startBeat: 8, endBeat: 4 } }))).toHaveLength(1);
    expect(planProblems(plan({ loop: { startBeat: 0, endBeat: 4 }, passes: 0 }))).toHaveLength(1);
    expect(planProblems(plan({ loop: { startBeat: 0, endBeat: 4 }, passes: 1000 }))).toHaveLength(1);
  });

  it("checks the speed trainer", () => {
    const loop = { startBeat: 0, endBeat: 4 };
    const ramp = { startPercent: 50, stepPercent: 10, everyPasses: 2, targetPercent: 80 };
    expect(planProblems(plan({ loop, ramp }))).toEqual([]);
    expect(planProblems(plan({ ramp }))).toEqual(["The speed trainer needs a loop to repeat."]);
    expect(planProblems(plan({ loop, ramp: { ...ramp, stepPercent: 0 } }))).toHaveLength(1);
    expect(planProblems(plan({ loop, ramp: { ...ramp, targetPercent: 40 } }))).toHaveLength(1);
    expect(planProblems(plan({ loop, ramp: { ...ramp, everyPasses: 0 } }))).toHaveLength(1);
    expect(planProblems(plan({ loop, ramp: { ...ramp, targetPercent: 300 } }))).toHaveLength(1);
  });
});

describe("speed trainer", () => {
  const ramp = { startPercent: 50, stepPercent: 10, everyPasses: 2, targetPercent: 80 };
  it("steps up every N passes and stops at the target", () => {
    const p = plan({ loop: { startBeat: 0, endBeat: 4 }, ramp });
    expect([0, 1, 2, 3, 4, 5, 6, 7, 8, 40].map((n) => passPercent(p, n))).toEqual([50, 50, 60, 60, 70, 70, 80, 80, 80, 80]);
    expect(passTempo(p, 0)).toBe(60);
    expect(passTempo(p, 6)).toBe(96);
  });
  it("uses the plain percentage when there is no ramp", () => {
    expect(passPercent(plan({ percent: 75 }), 9)).toBe(75);
  });
});

describe("timeline and position (whole piece)", () => {
  const p = plan(); // 16 beats at 120 BPM with a 4-beat count-in
  it("lays out the count-in and the music", () => {
    const t = passTiming(p, 0);
    near(t.startSeconds, 0);
    near(t.musicStartSeconds, 2);
    near(t.endSeconds, 10);
    near(planSeconds(p), 10);
    expect(timeline(p)).toHaveLength(1);
  });

  it("reports the count-in, then the beat", () => {
    expect(positionAt(p, 0)).toMatchObject({ inCountIn: true, countInBeat: 1, pass: 0, finished: false });
    expect(positionAt(p, 0.5)).toMatchObject({ inCountIn: true, countInBeat: 2 });
    expect(positionAt(p, 1.9)).toMatchObject({ inCountIn: true, countInBeat: 4 });
    const music = positionAt(p, 3);
    expect(music.inCountIn).toBe(false);
    near(music.beat, 2);
    expect(positionAt(p, 2).inCountIn).toBe(false);
    near(positionAt(p, 2).beat, 0);
  });

  it("finishes at the end and stays there", () => {
    const end = positionAt(p, 10);
    expect(end.finished).toBe(true);
    near(end.beat, 16);
    expect(positionAt(p, 999)).toMatchObject({ finished: true, beat: 16 });
    expect(positionAt(p, -5).inCountIn).toBe(true); // before the start counts as the start
  });

  it("works with no count-in", () => {
    const q = plan({ countInBeats: 0 });
    near(passTiming(q, 0).musicStartSeconds, 0);
    expect(positionAt(q, 0).inCountIn).toBe(false);
  });

  it("follows the practice speed", () => {
    const slow = plan({ percent: 50 }); // 60 BPM: a beat is a second
    near(planSeconds(slow), 4 + 16);
    near(positionAt(slow, 4 + 8).beat, 8);
  });
});

describe("timeline and position (loops)", () => {
  const loop = { startBeat: 4, endBeat: 8 };
  it("counts in once, then repeats back to back", () => {
    const p = plan({ loop, passes: 3 });
    const t = timeline(p);
    expect(t).toHaveLength(3);
    near(t[0]!.musicStartSeconds, 2);
    near(t[0]!.endSeconds, 4);
    near(t[1]!.startSeconds, 4);
    near(t[1]!.musicStartSeconds, 4);
    near(t[1]!.endSeconds, 6);
    near(t[2]!.endSeconds, 8);
    const at = positionAt(p, 5);
    expect(at.pass).toBe(1);
    near(at.beat, 6);
    expect(positionAt(p, 8).finished).toBe(true);
  });

  it("can count in before every pass", () => {
    const p = plan({ loop, passes: 2, countInEachPass: true });
    const t = timeline(p);
    near(t[1]!.startSeconds, 4);
    near(t[1]!.musicStartSeconds, 6);
    near(t[1]!.endSeconds, 8);
    expect(positionAt(p, 4.2)).toMatchObject({ pass: 1, inCountIn: true, countInBeat: 1 });
  });

  it("an open-ended loop is capped", () => {
    const p = plan({ loop, passes: null, countInBeats: 0 });
    expect(timeline(p)).toHaveLength(MAX_PASSES);
    expect(positionAt(p, 1e9).finished).toBe(true);
  });

  it("ignores the pass count without a loop", () => {
    expect(timeline(plan({ passes: 9 }))).toHaveLength(1);
  });

  it("speeds up pass by pass", () => {
    // 4 beats at 120 BPM base; 50% then 100%: pass 0 takes 4 s, the rest 2 s each
    const p = plan({
      loop: { startBeat: 0, endBeat: 4 }, passes: 4, countInBeats: 0,
      ramp: { startPercent: 50, stepPercent: 50, everyPasses: 1, targetPercent: 100 },
    });
    expect(timeline(p).map((x) => x.endSeconds)).toEqual([4, 6, 8, 10]);
    expect(timeline(p).map((x) => x.tempo)).toEqual([60, 120, 120, 120]);
    expect(positionAt(p, 5).tempo).toBe(120);
  });

  it("maps a beat to session time within a pass", () => {
    const p = plan({ loop, passes: 2 });
    near(timeAtBeat(p, 0, 6)!, 3);
    near(timeAtBeat(p, 1, 6)!, 5);
    expect(timeAtBeat(p, 0, 9)).toBeNull();
    expect(timeAtBeat(p, 5, 6)).toBeNull();
    expect(timeAtBeat(p, -1, 6)).toBeNull();
  });
});

describe("clicks", () => {
  it("clicks the count-in and every beat, accenting bar lines", () => {
    const p = plan({ totalBeats: 8 });
    const c = clicksForPass(p, 0);
    expect(c).toHaveLength(4 + 8);
    const count = c.filter((x) => x.countIn);
    expect(count.map((x) => x.time)).toEqual([0, 0.5, 1, 1.5]);
    expect(count.map((x) => x.accent)).toEqual([true, false, false, false]);
    expect(count.map((x) => x.beat)).toEqual([-4, -3, -2, -1]);
    const music = c.filter((x) => !x.countIn);
    expect(music.map((x) => x.beat)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(music.filter((x) => x.accent).map((x) => x.beat)).toEqual([0, 4]);
    near(music[0]!.time, 2);
    near(music[7]!.time, 5.5);
  });

  it("keeps the piece's bar grid when a loop starts mid-bar", () => {
    const p = plan({ loop: { startBeat: 2, endBeat: 6 }, countInBeats: 0, passes: 1 });
    const c = clicksForPass(p, 0);
    expect(c.map((x) => x.beat)).toEqual([2, 3, 4, 5]);
    expect(c.filter((x) => x.accent).map((x) => x.beat)).toEqual([4]);
  });

  it("clicks from the next whole beat when a loop starts between beats", () => {
    const p = plan({ loop: { startBeat: 2.5, endBeat: 5 }, countInBeats: 0, passes: 1 });
    expect(clicksForPass(p, 0).map((x) => x.beat)).toEqual([3, 4]);
  });

  it("accents each bar of a long count-in", () => {
    const p = plan({ countInBeats: 6 });
    expect(clicksForPass(p, 0).filter((x) => x.countIn).map((x) => x.accent)).toEqual([true, false, false, false, true, false]);
  });

  it("uses the bar length of the time signature", () => {
    const p = defaultPlan({ tempo: 120, time_signature: [3, 4], total_beats: 6 }, { countInBeats: 0 });
    expect(clicksForPass(p, 0).filter((x) => x.accent).map((x) => x.beat)).toEqual([0, 3]);
  });

  it("produces clicks lazily and in time order across passes", () => {
    const p = plan({ loop: { startBeat: 0, endBeat: 4 }, passes: null, countInBeats: 0 });
    const first: number[] = [];
    for (const c of allClicks(p)) {
      first.push(c.time);
      if (first.length === 10) break;
    }
    expect(first).toEqual([0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5]);
    const whole = [...allClicks(plan({ loop: { startBeat: 0, endBeat: 4 }, passes: 2 }))].map((c) => c.time);
    expect(whole).toEqual([...whole].sort((a, b) => a - b));
  });

  it("clicks at the practice speed, including a ramp", () => {
    const p = plan({
      loop: { startBeat: 0, endBeat: 2 }, passes: 2, countInBeats: 0,
      ramp: { startPercent: 50, stepPercent: 50, everyPasses: 1, targetPercent: 100 },
    });
    expect([...allClicks(p)].map((c) => c.time)).toEqual([0, 1, 2, 2.5]);
  });
});

describe("notes of a pass", () => {
  const events = [
    { midi: 60, hand: "R" as const, start_beat: 3, duration_beats: 2, chord_index: 0 }, // starts before the loop
    { midi: 62, hand: "R" as const, start_beat: 4, duration_beats: 1, chord_index: 1 },
    { midi: 48, hand: "L" as const, start_beat: 4, duration_beats: 4, chord_index: 1 },
    { midi: 64, hand: "R" as const, start_beat: 5, duration_beats: 4, chord_index: 1 }, // runs past the end
    { midi: 65, hand: "R" as const, start_beat: 8, duration_beats: 1, chord_index: 2 }, // after the loop
  ];
  const p = plan({ loop: { startBeat: 4, endBeat: 8 }, passes: 2, countInBeats: 0 });

  it("keeps notes that start in the loop, cut at its end, in session time", () => {
    const n = notesForPass(p, 0, events);
    expect(n.map((x) => x.midi)).toEqual([48, 62, 64]);
    expect(n.map((x) => x.startSeconds)).toEqual([0, 0, 0.5]);
    expect(n.find((x) => x.midi === 64)!.durationSeconds).toBe(1.5); // 3 beats left in the loop
    expect(n.find((x) => x.midi === 48)!.durationSeconds).toBe(2);
  });

  it("places the next pass after the first", () => {
    const n = notesForPass(p, 1, events);
    expect(n[0]!.startSeconds).toBe(2);
  });

  it("leaves out a muted hand", () => {
    expect(notesForPass(p, 0, events, { L: false, R: true }).map((x) => x.midi)).toEqual([62, 64]);
    expect(notesForPass(p, 0, events, { L: false, R: false })).toEqual([]);
  });
});

describe("hand-off to scoring", () => {
  it("whole piece: offset is the start of the music, no beat range", () => {
    expect(scoringParams(plan(), 0)).toEqual({ tempo_bpm: 120, offset_s: 2, beat_range: null });
  });

  it("loop: offset is where beat 0 would be, even mid-piece", () => {
    const p = plan({ loop: { startBeat: 4, endBeat: 8 }, passes: 3 });
    expect(scoringParams(p, 0)).toEqual({ tempo_bpm: 120, offset_s: 0, beat_range: [4, 8] }); // 2 s count-in - 4 beats
    expect(scoringParams(p, 1)).toEqual({ tempo_bpm: 120, offset_s: 2, beat_range: [4, 8] });
    expect(scoringParams(p, 2).offset_s).toBe(4);
  });

  it("uses the tempo of the pass", () => {
    const p = plan({
      loop: { startBeat: 0, endBeat: 4 }, passes: 2, countInBeats: 0,
      ramp: { startPercent: 50, stepPercent: 50, everyPasses: 1, targetPercent: 100 },
    });
    expect(scoringParams(p, 0).tempo_bpm).toBe(60);
    expect(scoringParams(p, 1)).toEqual({ tempo_bpm: 120, offset_s: 4, beat_range: [0, 4] });
  });

  it("agrees with where the notes are actually scheduled", () => {
    // The scoring API puts a note at offset + beat * (60 / tempo). That must be the second the
    // player is asked to play it, for every pass, loop and ramp.
    const events = [0, 1, 2, 3, 4, 5, 6, 7].map((b) => ({ midi: 60 + b, hand: "R" as const, start_beat: b, duration_beats: 1, chord_index: b }));
    const p = plan({
      loop: { startBeat: 2, endBeat: 6 }, passes: 4, countInEachPass: true,
      ramp: { startPercent: 60, stepPercent: 20, everyPasses: 1, targetPercent: 100 },
    });
    for (let pass = 0; pass < 4; pass++) {
      const s = scoringParams(p, pass);
      for (const n of notesForPass(p, pass, events)) {
        expect(s.offset_s + n.beat * (60 / s.tempo_bpm)).toBeCloseTo(n.startSeconds, 9);
      }
    }
  });
});
