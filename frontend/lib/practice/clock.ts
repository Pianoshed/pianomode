/** The practice clock (Phase 7, step 2): pure functions, no audio, no React, no real clock.
 *
 *  A practice *plan* says how a piece is practised: at what tempo, with what count-in, over what
 *  loop, for how many passes, and whether the tempo steps up as passes go by. From a plan this
 *  module answers every timing question the practice screen and the metronome have:
 *  where each pass starts, which beat is sounding at a given second, when each click falls, and
 *  which parameters to send to the scoring API for a pass.
 *
 *  Conventions (they match the movement library):
 *  - Beats are the movement's own beat unit, counted from 0. A bar holds `beatsPerBar` of them,
 *    the time signature's numerator, so 6/8 clicks six times a bar.
 *  - Session seconds start at 0 when the plan starts, count-in included. These are the same
 *    seconds in which played notes are recorded, which is what scoring needs.
 *  - Clicks fall on whole beats. A loop that starts between beats clicks from the next whole beat.
 *  - The bar grid belongs to the piece, so a loop that starts mid-bar still accents bar lines
 *    where the piece has them.
 */

export const MIN_TEMPO = 20;
export const MAX_TEMPO = 400;
export const MIN_PERCENT = 10;
export const MAX_PERCENT = 200;
export const MAX_COUNT_IN = 16;
/** A plan with no fixed number of passes still plays at most this many before stopping. */
export const MAX_PASSES = 500;
const EPS = 1e-9;

export type LoopRegion = { startBeat: number; endBeat: number };
/** Speed trainer: start at `startPercent` of the base tempo and add `stepPercent` after every
 *  `everyPasses` passes, never going above `targetPercent`. */
export type Ramp = { startPercent: number; stepPercent: number; everyPasses: number; targetPercent: number };

export type PracticePlan = {
  baseTempo: number; // the piece's own tempo, in beats per minute
  percent: number; // practice speed as a percentage of the base tempo (ignored when `ramp` is set)
  beatsPerBar: number;
  totalBeats: number;
  countInBeats: number; // 0 for none; clicked before the first pass
  countInEachPass: boolean; // repeat the count-in before every pass of a loop
  loop: LoopRegion | null;
  passes: number | null; // null: keep going (up to MAX_PASSES). Ignored without a loop: one pass
  ramp: Ramp | null;
};

export const clampTempo = (bpm: number): number => Math.min(MAX_TEMPO, Math.max(MIN_TEMPO, bpm));
const round1 = (n: number): number => Math.round(n * 10) / 10;

/** Practice tempo for a base tempo and a speed percentage, kept inside the supported range. */
export function effectiveTempo(baseTempo: number, percent: number): number {
  return round1(clampTempo((baseTempo * Math.min(MAX_PERCENT, Math.max(MIN_PERCENT, percent))) / 100));
}

export function defaultPlan(
  piece: { tempo: number; time_signature: number[]; total_beats: number },
  overrides: Partial<PracticePlan> = {},
): PracticePlan {
  const beatsPerBar = Math.max(1, Math.round(piece.time_signature[0] ?? 4));
  return {
    baseTempo: piece.tempo,
    percent: 100,
    beatsPerBar,
    totalBeats: piece.total_beats,
    countInBeats: beatsPerBar,
    countInEachPass: false,
    loop: null,
    passes: null,
    ramp: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------- loops

/** Why a loop is not usable, or null. Needs at least one beat, inside the piece. */
export function loopProblem(region: LoopRegion, totalBeats: number): string | null {
  const { startBeat, endBeat } = region;
  if (!Number.isFinite(startBeat) || !Number.isFinite(endBeat)) return "The loop needs a start and an end.";
  if (startBeat < 0) return "The loop cannot start before the piece.";
  if (endBeat > totalBeats + EPS) return "The loop cannot end after the piece.";
  if (endBeat - startBeat < 1 - EPS) return "The loop must be at least one beat long.";
  return null;
}

/** Widen a loop outward to whole bars so it starts and ends on bar lines. */
export function snapLoopToBars(region: LoopRegion, beatsPerBar: number, totalBeats: number): LoopRegion {
  const bar = Math.max(1, beatsPerBar);
  const startBeat = Math.max(0, Math.floor(region.startBeat / bar + EPS) * bar);
  const endBeat = Math.min(totalBeats, Math.ceil(region.endBeat / bar - EPS) * bar);
  return { startBeat, endBeat };
}

/** A loop covering chords `from` to `to` (inclusive, either order). */
export function loopFromSteps(
  steps: readonly { beat: number; duration: number }[],
  from: number,
  to: number,
  totalBeats: number,
): LoopRegion | null {
  if (steps.length === 0) return null;
  const a = Math.min(Math.max(0, Math.min(from, to)), steps.length - 1);
  const b = Math.min(Math.max(0, Math.max(from, to)), steps.length - 1);
  const first = steps[a] as { beat: number; duration: number };
  const last = steps[b] as { beat: number; duration: number };
  return { startBeat: first.beat, endBeat: Math.min(totalBeats, last.beat + last.duration) };
}

// ---------------------------------------------------------------- plan checks

/** Every reason a plan cannot be played. Empty means it can. */
export function planProblems(plan: PracticePlan): string[] {
  const out: string[] = [];
  if (!(plan.baseTempo >= MIN_TEMPO && plan.baseTempo <= MAX_TEMPO)) out.push(`The tempo must be ${MIN_TEMPO} to ${MAX_TEMPO} BPM.`);
  if (!Number.isInteger(plan.beatsPerBar) || plan.beatsPerBar < 1) out.push("Beats per bar must be a whole number, 1 or more.");
  if (!(plan.totalBeats > 0)) out.push("The piece has no length.");
  if (!Number.isInteger(plan.countInBeats) || plan.countInBeats < 0 || plan.countInBeats > MAX_COUNT_IN) out.push(`The count-in must be 0 to ${MAX_COUNT_IN} beats.`);
  if (plan.loop) {
    const p = loopProblem(plan.loop, plan.totalBeats);
    if (p) out.push(p);
  }
  if (plan.passes !== null && (!Number.isInteger(plan.passes) || plan.passes < 1 || plan.passes > MAX_PASSES)) out.push(`Passes must be 1 to ${MAX_PASSES}, or left open.`);
  if (!plan.ramp && !(plan.percent >= MIN_PERCENT && plan.percent <= MAX_PERCENT)) out.push(`Speed must be ${MIN_PERCENT}% to ${MAX_PERCENT}%.`);
  const r = plan.ramp;
  if (r) {
    if (!plan.loop) out.push("The speed trainer needs a loop to repeat.");
    if (r.startPercent < MIN_PERCENT || r.targetPercent > MAX_PERCENT) out.push(`Speeds must stay between ${MIN_PERCENT}% and ${MAX_PERCENT}%.`);
    if (r.stepPercent <= 0) out.push("The speed step must be above 0.");
    if (r.targetPercent < r.startPercent) out.push("The target speed cannot be below the starting speed.");
    if (!Number.isInteger(r.everyPasses) || r.everyPasses < 1) out.push("Speed up after a whole number of passes, 1 or more.");
  }
  return out;
}

/** Speed percentage used for a pass (0-based). */
export function passPercent(plan: PracticePlan, pass: number): number {
  const r = plan.ramp;
  if (!r) return plan.percent;
  const steps = Math.floor(Math.max(0, pass) / Math.max(1, r.everyPasses));
  return Math.min(r.targetPercent, r.startPercent + steps * r.stepPercent);
}

export const passTempo = (plan: PracticePlan, pass: number): number => effectiveTempo(plan.baseTempo, passPercent(plan, pass));

export const passBounds = (plan: PracticePlan): LoopRegion => plan.loop ?? { startBeat: 0, endBeat: plan.totalBeats };
export const passCount = (plan: PracticePlan): number => (plan.loop ? (plan.passes ?? MAX_PASSES) : 1);

// ---------------------------------------------------------------- timeline

export type PassTiming = {
  index: number;
  tempo: number;
  percent: number;
  startBeat: number;
  endBeat: number;
  countInBeats: number;
  startSeconds: number; // where this pass (its count-in, if any) begins in session time
  musicStartSeconds: number; // where startBeat sounds
  endSeconds: number;
};

/** Lay the first `count` passes end to end. The single place pass timing is computed. */
function layout(plan: PracticePlan, count: number): PassTiming[] {
  const bounds = passBounds(plan);
  const length = bounds.endBeat - bounds.startBeat;
  const out: PassTiming[] = [];
  let cursor = 0;
  for (let i = 0; i < count; i++) {
    const percent = passPercent(plan, i);
    const tempo = effectiveTempo(plan.baseTempo, percent);
    const spb = 60 / tempo;
    const countIn = i === 0 || plan.countInEachPass ? plan.countInBeats : 0;
    const musicStart = cursor + countIn * spb;
    const end = musicStart + length * spb;
    out.push({
      index: i, tempo, percent, startBeat: bounds.startBeat, endBeat: bounds.endBeat, countInBeats: countIn,
      startSeconds: cursor, musicStartSeconds: musicStart, endSeconds: end,
    });
    cursor = end;
  }
  return out;
}

/** Timing of one pass (0-based). */
export const passTiming = (plan: PracticePlan, pass: number): PassTiming => layout(plan, pass + 1)[pass] as PassTiming;

/** Timing of every pass. */
export const timeline = (plan: PracticePlan): PassTiming[] => layout(plan, passCount(plan));

export const planSeconds = (plan: PracticePlan): number => (timeline(plan).at(-1)?.endSeconds ?? 0);

export type Position = {
  pass: number;
  beat: number; // the piece beat sounding now (the loop start during a count-in)
  inCountIn: boolean;
  countInBeat: number | null; // 1-based count-in beat while counting in
  tempo: number;
  finished: boolean;
};

/** Where the practice is `seconds` after it started. After the last pass `finished` is true and
 *  the position stays at the end of that pass. */
export function positionAt(plan: PracticePlan, seconds: number): Position {
  const passes = timeline(plan);
  const t = Math.max(0, seconds);
  for (const p of passes) {
    if (t < p.endSeconds - EPS) {
      const spb = 60 / p.tempo;
      if (t < p.musicStartSeconds - EPS) {
        const n = Math.min(p.countInBeats, Math.floor((t - p.startSeconds) / spb + EPS) + 1);
        return { pass: p.index, beat: p.startBeat, inCountIn: true, countInBeat: n, tempo: p.tempo, finished: false };
      }
      return { pass: p.index, beat: p.startBeat + (t - p.musicStartSeconds) / spb, inCountIn: false, countInBeat: null, tempo: p.tempo, finished: false };
    }
  }
  const last = passes.at(-1) as PassTiming;
  return { pass: last.index, beat: last.endBeat, inCountIn: false, countInBeat: null, tempo: last.tempo, finished: true };
}

/** Session time at which `beat` sounds during `pass`, or null if the pass does not cover it. */
export function timeAtBeat(plan: PracticePlan, pass: number, beat: number): number | null {
  if (pass < 0 || pass >= passCount(plan)) return null;
  const p = passTiming(plan, pass);
  if (beat < p.startBeat - EPS || beat > p.endBeat + EPS) return null;
  return p.musicStartSeconds + (beat - p.startBeat) * (60 / p.tempo);
}

// ---------------------------------------------------------------- clicks

export type Click = {
  time: number; // session seconds
  beat: number; // piece beat; count-in clicks use the beats just before the loop start
  accent: boolean; // first beat of a bar (or of a count-in bar)
  countIn: boolean;
  pass: number;
};

/** Clicks for one pass: its count-in, then a click on every whole beat of the music. */
export function clicksForPass(plan: PracticePlan, pass: number): Click[] {
  const p = passTiming(plan, pass);
  const spb = 60 / p.tempo;
  const bar = plan.beatsPerBar;
  const out: Click[] = [];
  for (let i = 0; i < p.countInBeats; i++) {
    out.push({ time: p.startSeconds + i * spb, beat: p.startBeat - (p.countInBeats - i), accent: i % bar === 0, countIn: true, pass });
  }
  for (let b = Math.ceil(p.startBeat - EPS) + 0; b < p.endBeat - EPS; b++) {  // + 0 turns -0 into 0
    out.push({ time: p.musicStartSeconds + (b - p.startBeat) * spb, beat: b, accent: ((b % bar) + bar) % bar === 0, countIn: false, pass });
  }
  return out;
}

/** Every click of the plan in time order, produced lazily so an open-ended loop costs nothing
 *  until it is played. */
export function* allClicks(plan: PracticePlan): Generator<Click> {
  const n = passCount(plan);
  for (let i = 0; i < n; i++) yield* clicksForPass(plan, i);
}

// ---------------------------------------------------------------- notes of a pass

export type TimedNote = { midi: number; hand: "L" | "R"; startSeconds: number; durationSeconds: number; chordIndex: number; beat: number };

/** The music's notes that sound in one pass, placed in session time. A note that starts before
 *  the loop and is still sounding at its start is not replayed; one that runs past the end is cut
 *  at the loop end. Muted hands are left out. */
export function notesForPass(
  plan: PracticePlan,
  pass: number,
  events: readonly { midi: number; hand: "L" | "R"; start_beat: number; duration_beats: number; chord_index: number }[],
  hands: { L: boolean; R: boolean } = { L: true, R: true },
): TimedNote[] {
  const p = passTiming(plan, pass);
  const spb = 60 / p.tempo;
  const out: TimedNote[] = [];
  for (const e of events) {
    if (!hands[e.hand]) continue;
    if (e.start_beat < p.startBeat - EPS || e.start_beat >= p.endBeat - EPS) continue;
    const length = Math.min(e.duration_beats, p.endBeat - e.start_beat);
    out.push({
      midi: e.midi, hand: e.hand, chordIndex: e.chord_index, beat: e.start_beat,
      startSeconds: p.musicStartSeconds + (e.start_beat - p.startBeat) * spb, durationSeconds: length * spb,
    });
  }
  return out.sort((a, b) => a.startSeconds - b.startSeconds || a.midi - b.midi);
}

// ---------------------------------------------------------------- scoring hand-off

export type ScoringParams = { tempo_bpm: number; offset_s: number; beat_range: [number, number] | null };

/** The values the scoring API needs for one pass, so a player's notes (recorded in session
 *  seconds) are scored against the right beats. `offset_s` is the session time of beat 0, even
 *  when the pass starts mid-piece. */
export function scoringParams(plan: PracticePlan, pass: number): ScoringParams {
  const p = passTiming(plan, pass);
  const spb = 60 / p.tempo;
  const whole = !plan.loop;
  return {
    tempo_bpm: p.tempo,
    offset_s: Math.max(0, p.musicStartSeconds - p.startBeat * spb),
    beat_range: whole ? null : [p.startBeat, p.endBeat],
  };
}
