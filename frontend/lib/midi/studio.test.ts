import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import analysis from "./__fixtures__/c-am-f-g.analysis.json";
import pyRequest from "./__fixtures__/c-am-f-g.request.json";
import type { AnalyzeResponse, NoteOut, Segment } from "./api";
import { type ParsedMidi, parseMidi } from "./smf";
import {
  MAX_EVENTS,
  type RequestOptions,
  StudioError,
  applyTrackEdits,
  barStarts,
  buildAnalyzeRequest,
  eventsBetween,
  flipHand,
  freeTrack,
  formatTime,
  makeRollView,
  midiNoteName,
  neighbour,
  noteAtPoint,
  noteKey,
  notesSounding,
  overlayForMoment,
  MAX_RATE_RETRIES,
  pumpEvents,
  rateLimitAdvice,
  rollX,
  rollY,
  secondsAtX,
  segmentAt,
  segmentLook,
  stepSelection,
  summarizeTracks,
  totalSeconds,
  windowFrom,
  withHands,
} from "./studio";

const parsed: ParsedMidi = parseMidi(new Uint8Array(readFileSync(new URL("./__fixtures__/c-am-f-g.mid", import.meta.url))));
const response = analysis as unknown as AnalyzeResponse;
const BAR = 1920;
const opts = (over: Partial<RequestOptions> = {}): RequestOptions => ({ grid: "beat", prefer: "sharps", key: null, trackStates: {}, ...over });
const evKey = (e: { tick: number; kind: string; note: number; track: number }) => `${e.tick}:${e.kind}:${e.note}:${e.track}`;

describe("applyTrackEdits", () => {
  it("merges tracks onto one without losing notes or changing the originals", () => {
    const out = applyTrackEdits(parsed.notes, [{ type: "merge", from: [1], into: 2 }]);
    expect(out).toHaveLength(parsed.notes.length);
    expect(new Set(out.map((n) => n.track))).toEqual(new Set([2]));
    expect(new Set(parsed.notes.map((n) => n.track))).toEqual(new Set([1, 2])); // untouched
  });
  it("splits a track by pitch onto a free track", () => {
    const out = applyTrackEdits(parsed.notes, [{ type: "split", track: 1, pitch: 62, into: 5 }]);
    expect(out.filter((n) => n.track === 5).every((n) => n.note >= 62)).toBe(true);
    expect(out.filter((n) => n.track === 1).every((n) => n.note < 62)).toBe(true);
    expect(out.filter((n) => n.track === 5).length).toBeGreaterThan(0);
  });
  it("refuses to split onto a track that already has notes, and to merge a track into itself", () => {
    expect(() => applyTrackEdits(parsed.notes, [{ type: "split", track: 1, pitch: 62, into: 2 }])).toThrowError(expect.objectContaining({ code: "track_in_use" }));
    expect(() => applyTrackEdits(parsed.notes, [{ type: "merge", from: [1, 2], into: 2 }])).toThrowError(StudioError);
  });
  it("applies edits in order", () => {
    const out = applyTrackEdits(parsed.notes, [{ type: "merge", from: [2], into: 1 }, { type: "split", track: 1, pitch: 50, into: 9 }]);
    expect(new Set(out.map((n) => n.track))).toEqual(new Set([1, 9]));
    expect(out.filter((n) => n.track === 1).every((n) => n.note < 50)).toBe(true);
  });
});

describe("summarizeTracks and freeTrack", () => {
  it("lists tracks that have notes, with their names and ranges", () => {
    const s = summarizeTracks(parsed, []);
    expect(s.map((t) => [t.index, t.name, t.noteCount])).toEqual([[1, "Right hand", 13], [2, "Left hand", 4]]);
    expect(s[0]).toMatchObject({ lowest: 57, highest: 69 });
  });
  it("labels a merged track and the upper part of a split", () => {
    expect(summarizeTracks(parsed, [{ type: "merge", from: [1], into: 2 }]).map((t) => t.name)).toEqual(["Left hand (merged)"]);
    const split = summarizeTracks(parsed, [{ type: "split", track: 1, pitch: 62, into: 5 }]);
    expect(split.map((t) => t.name)).toEqual(["Right hand", "Left hand", "Right hand (upper part)"]);
    expect(split.find((t) => t.index === 5)!.derived).toBe(true);
  });
  it("finds a free track number, skipping ones already planned", () => {
    expect(freeTrack(parsed, [])).toBe(0);
    expect(freeTrack(parsed, [{ type: "split", track: 1, pitch: 62, into: 0 }])).toBe(3);
  });
});

describe("bars and windows", () => {
  it("counts bars in 4/4, 3/4 and 6/8", () => {
    expect(barStarts(480, [], 5000)).toEqual([0, 1920, 3840]);
    expect(barStarts(480, [{ tick: 0, numerator: 3, denominator: 4 }], 3000)).toEqual([0, 1440, 2880]);
    expect(barStarts(480, [{ tick: 0, numerator: 6, denominator: 8 }], 3000)).toEqual([0, 1440, 2880]);
  });
  it("follows a change of time signature", () => {
    const starts = barStarts(480, [{ tick: 0, numerator: 4, denominator: 4 }, { tick: 3840, numerator: 3, denominator: 4 }], 7000);
    expect(starts).toEqual([0, 1920, 3840, 5280, 6720]);
  });
  it("takes the whole file when it fits", () => {
    const w = windowFrom(parsed, 0);
    expect(w).toMatchObject({ fromBar: 0, toBar: 4, totalBars: 4, noteCount: 17, whole: true, startTick: 0, endTick: Infinity });
  });
  it("takes as many bars as fit, and the next window carries on from there", () => {
    const first = windowFrom(parsed, 0, 9);
    expect(first).toMatchObject({ fromBar: 0, toBar: 2, noteCount: 8, whole: false, endTick: 2 * BAR });
    const next = neighbour(parsed, first, 1, 9)!;
    expect(next).toMatchObject({ fromBar: 2, toBar: 4, noteCount: 9 });
    expect(neighbour(parsed, next, 1, 9)).toBeNull();
  });
  it("can step back, ending exactly where the current window begins", () => {
    const last = windowFrom(parsed, 2, 9);
    const prev = neighbour(parsed, last, -1, 9)!;
    expect(prev.toBar).toBe(2);
    expect(prev.endTick).toBe(2 * BAR);
    expect(neighbour(parsed, windowFrom(parsed, 0, 9), -1, 9)).toBeNull();
  });
  it("a bar too dense to analyse is an error that says so", () => {
    expect(() => windowFrom(parsed, 0, 3)).toThrowError(expect.objectContaining({ code: "too_dense" }));
  });
  it("clamps a start bar outside the file", () => {
    expect(windowFrom(parsed, 99).fromBar).toBe(3);
    expect(windowFrom(parsed, -4).fromBar).toBe(0);
  });
});

describe("buildAnalyzeRequest", () => {
  it("builds exactly the events the independent Python writer produced", () => {
    const req = buildAnalyzeRequest(parsed, parsed.notes, windowFrom(parsed, 0), opts());
    expect(req.events.map(evKey).sort()).toEqual(pyRequest.events.map(evKey).sort());
    expect(req.ppq).toBe(pyRequest.ppq);
    expect(req.tempo_changes).toEqual(pyRequest.tempo_changes);
    expect(req.time_signatures).toEqual(pyRequest.time_signatures);
  });
  it("shifts a partial window to tick 0 and cuts notes at its end", () => {
    const w = windowFrom(parsed, 0, 9); // bars 1-2
    const req = buildAnalyzeRequest(parsed, parsed.notes, w, opts());
    expect(req.events.length).toBe(16);
    expect(Math.max(...req.events.map((e) => e.tick))).toBeLessThanOrEqual(2 * BAR);
    const second = windowFrom(parsed, 2, 9);
    const r2 = buildAnalyzeRequest(parsed, parsed.notes, second, opts());
    expect(Math.min(...r2.events.map((e) => e.tick))).toBe(0);
    expect(r2.events.filter((e) => e.kind === "note_on")).toHaveLength(9);
  });
  it("carries the tempo and time signature in effect at the window start", () => {
    const p: ParsedMidi = { ...parsed, tempoChanges: [{ tick: 0, bpm: 100 }, { tick: BAR + 480, bpm: 140 }, { tick: 3 * BAR, bpm: 90 }], timeSignatures: [{ tick: 0, numerator: 4, denominator: 4 }, { tick: 2 * BAR, numerator: 3, denominator: 4 }] };
    const w = { fromBar: 2, toBar: 4, totalBars: 4, startTick: 2 * BAR, endTick: Infinity, noteCount: 9, whole: false };
    const req = buildAnalyzeRequest(p, p.notes, w, opts());
    expect(req.tempo_changes).toEqual([{ tick: 0, bpm: 140 }, { tick: BAR, bpm: 90 }]);
    expect(req.time_signatures).toEqual([{ tick: 0, numerator: 3, denominator: 4 }]);
  });
  it("sends one state per track that has notes in the window, including names, hands, mute and solo", () => {
    const req = buildAnalyzeRequest(parsed, parsed.notes, windowFrom(parsed, 0), opts({ trackStates: { 1: { hand: "R", muted: false, solo: true }, 2: { hand: null, muted: true, solo: false } }, trackNames: { 1: "Right hand" } }));
    expect(req.track_states).toEqual([
      { track: 1, name: "Right hand", hand: "R", muted: false, solo: true },
      { track: 2, name: null, hand: null, muted: true, solo: false },
    ]);
  });
  it("passes the chosen key, grid and spelling through", () => {
    const req = buildAnalyzeRequest(parsed, parsed.notes, windowFrom(parsed, 0), opts({ key: { tonic: "A", mode: "minor" }, grid: "bar", prefer: "flats" }));
    expect(req).toMatchObject({ key: { tonic: "A", mode: "minor" }, grid: "bar", prefer: "flats", include_notes: true });
  });
  it("applies track edits through the notes it is given", () => {
    const merged = applyTrackEdits(parsed.notes, [{ type: "merge", from: [1], into: 2 }]);
    const req = buildAnalyzeRequest(parsed, merged, windowFrom(parsed, 0), opts());
    expect(new Set(req.events.map((e) => e.track))).toEqual(new Set([2]));
  });
  it("refuses a request over the event limit", () => {
    const many = Array.from({ length: MAX_EVENTS / 2 + 1 }, (_, i) => ({ ...parsed.notes[0]!, index: i, startTick: i, endTick: i + 5 }));
    const w = { fromBar: 0, toBar: 1, totalBars: 1, startTick: 0, endTick: Infinity, noteCount: many.length, whole: true };
    expect(() => buildAnalyzeRequest(parsed, many, w, opts())).toThrowError(expect.objectContaining({ code: "too_many_events" }));
  });
});

describe("hands", () => {
  const notes = response.notes!;
  const first = notes[0]!;
  const keyOf = (n: NoteOut, offset = 0) => noteKey(Math.round(n.start_beat * 480) + offset, n.midi, n.channel);
  it("an edit on a note wins over a track tag and over the suggestion", () => {
    const edits = new Map([[keyOf(first), first.hand === "L" ? ("R" as const) : ("L" as const)]]);
    const out = withHands(notes, 480, 0, edits, { [first.track]: "L" });
    expect(out[0]).toMatchObject({ hand: edits.get(keyOf(first)), handSource: "user" });
  });
  it("a track assigned to one hand sets its notes", () => {
    const out = withHands(notes, 480, 0, new Map(), { 1: "L" });
    expect(out.filter((n) => n.track === 1).every((n) => n.hand === "L" && n.handSource === "track")).toBe(true);
    expect(out.filter((n) => n.track === 2).every((n) => n.handSource === "auto")).toBe(true);
  });
  it("tags 'both' and 'other' do not force a hand", () => {
    const out = withHands(notes, 480, 0, new Map(), { 1: "both", 2: "other" });
    expect(out.every((n) => n.handSource === "auto")).toBe(true);
  });
  it("note keys are stable across windows: the same note gets the same key", () => {
    const shifted = { ...first, start_beat: first.start_beat - 8 }; // as if the window began two bars later
    expect(keyOf(first)).toBe(noteKey(Math.round(shifted.start_beat * 480) + 8 * 480, first.midi, first.channel));
    const out = withHands([shifted], 480, 8 * 480, new Map([[keyOf(first), "R"]]), {});
    expect(out[0]!.handSource).toBe("user");
  });
  it("flipHand toggles, treating no hand as left-to-right", () => {
    expect(flipHand("L")).toBe("R");
    expect(flipHand("R")).toBe("L");
    expect(flipHand(null)).toBe("L");
  });
});

describe("playback helpers", () => {
  const hn = withHands(response.notes!, 480, 0, new Map(), {});
  it("groups notes that start and end together and makes times relative", () => {
    // 100 BPM in 4/4: a bar lasts 2.4 seconds. Bar 1's four notes share one start and length.
    const first = eventsBetween(hn, 0, 2, "both");
    expect(first).toHaveLength(1);
    expect(first[0]!.start).toBe(0);
    expect([...first[0]!.notes].sort((a, b) => a - b)).toEqual([48, 60, 64, 67]);
    const second = eventsBetween(hn, 2, 4, "both");
    expect(second[0]!.start).toBeCloseTo(0.4, 3);
  });
  it("isolates a hand", () => {
    const left = eventsBetween(hn, 0, 20, "L").flatMap((e) => e.notes);
    const right = eventsBetween(hn, 0, 20, "R").flatMap((e) => e.notes);
    expect(left.length + right.length).toBe(17);
    expect(Math.max(...left)).toBeLessThan(Math.min(...right) + 12);
  });
  it("only notes starting inside the span are returned (the caller schedules in chunks)", () => {
    expect(eventsBetween(hn, 100, 200, "both")).toEqual([]);
    expect(eventsBetween(hn, 0, 0, "both")).toEqual([]);
  });
  it("finds the notes and the chord sounding at a time", () => {
    expect(notesSounding(hn, 1).map((n) => n.midi).sort()).toEqual([48, 60, 64, 67]);
    expect(notesSounding(hn, 1000)).toEqual([]);
    expect(segmentAt(response.segments, 0.5)!.candidates[0]!.symbol).toBe("C");
    expect(segmentAt(response.segments, 3)!.candidates[0]!.symbol).toBe("Am");
    expect(segmentAt(response.segments, 5)!.candidates[0]!.symbol).toBe("F");
    expect(segmentAt(response.segments, 9999)).toBeNull();
  });
  it("the total length covers the last note", () => {
    expect(totalSeconds(response)).toBeCloseTo(Math.max(...response.notes!.map((n) => n.end_sec)), 6);
    expect(totalSeconds({ segments: [], notes: null })).toBe(0);
  });
});

describe("contract and chord display (the API's real response)", () => {
  it("has the four chords, numerals and a key estimate marked as estimated", () => {
    expect(response.segments.map((s) => s.candidates[0]!.symbol)).toEqual(["C", "Am", "F", "G7"]);
    expect(response.segments.map((s) => s.numeral!.figure)).toEqual(["I", "vi", "IV", "V7"]);
    expect(response.key!.name).toBe("C major");
    expect(response.key_source).toBe("estimated");
  });
  it("labels segments, marking ambiguity and unknowns honestly", () => {
    expect(segmentLook(response.segments[0]!)).toEqual({ label: "C", sublabel: "I", kind: "identified" });
    const amb: Segment = { ...response.segments[1]!, status: "ambiguous" };
    expect(segmentLook(amb)).toMatchObject({ label: "Am?", kind: "ambiguous" });
    expect(segmentLook({ ...amb, status: "no_reliable_label", candidates: [] })).toEqual({ label: "?", sublabel: null, kind: "unknown" });
    expect(segmentLook({ ...amb, status: "silence", candidates: [] })).toEqual({ label: "", sublabel: null, kind: "silence" });
  });
});

describe("overlayForMoment", () => {
  const hn = withHands(response.notes!, 480, 0, new Map(), {});
  it("colours the sounding notes by the chord reading and shows the hands", () => {
    const o = overlayForMoment(notesSounding(hn, 1), segmentAt(response.segments, 1))!;
    expect([...o.marks.keys()].sort()).toEqual([48, 60, 64, 67]);
    expect(o.marks.get(60)!.role).toBe("root");
    expect(o.marks.get(64)!.role).toBe("tone");
    expect(o.title).toBe("C");
    expect(o.marks.get(48)!.hand).toBe("L");
    expect(o.marks.get(67)!.hand).toBe("R");
  });
  it("marks exactly one bass note, the lowest", () => {
    const o = overlayForMoment(notesSounding(hn, 1), segmentAt(response.segments, 1))!;
    expect([...o.marks.entries()].filter(([, m]) => m.bass).map(([k]) => k)).toEqual([48]);
  });
  it("with no chord reading, notes are still shown with their names and hands", () => {
    const o = overlayForMoment(notesSounding(hn, 1), null)!;
    expect(o.marks.get(60)!.label).toBe("C");
    expect(o.marks.get(60)!.role).toBe("tone");
    expect(o.title).toBe("");
  });
  it("shows nothing when nothing is sounding", () => {
    expect(overlayForMoment([], response.segments[0]!)).toBeNull();
  });
});

describe("piano roll geometry", () => {
  const view = makeRollView(response.notes!, 16, 40);
  it("always shows at least two octaves and stays inside the MIDI range", () => {
    expect(view.hi - view.lo).toBeGreaterThanOrEqual(23);
    expect(makeRollView([], 10, 40)).toMatchObject({ lo: 48, hi: 72 });
    const extreme = makeRollView([{ midi: 0 }, { midi: 127 }], 5, 40);
    expect(extreme.lo).toBe(0);
    expect(extreme.hi).toBe(127);
  });
  it("finds the note under a point, and nothing in empty space", () => {
    const n = response.notes![0]!;
    const x = rollX(view, (n.start_sec + n.end_sec) / 2);
    const y = rollY(view, n.midi) + 2;
    expect(noteAtPoint(response.notes!, view, x, y)?.midi).toBe(n.midi);
    expect(noteAtPoint(response.notes!, view, 2, 2)).toBeNull();
  });
  it("turns a pixel into a time inside the piece", () => {
    expect(secondsAtX(view, view.left + 80)).toBeCloseTo(2);
    expect(secondsAtX(view, -50)).toBe(0);
    expect(secondsAtX(view, 99999)).toBe(16);
  });
  it("steps through notes in order and stops at the ends", () => {
    const ns = response.notes!;
    expect(stepSelection(ns, null, 1)).toBe(ns[0]);
    expect(stepSelection(ns, null, -1)).toBe(ns.at(-1));
    expect(stepSelection(ns, ns[0]!, 1)).toBe(ns[1]);
    expect(stepSelection(ns, ns[0]!, -1)).toBe(ns[0]);
    expect(stepSelection(ns, ns.at(-1)!, 1)).toBe(ns.at(-1));
    expect(stepSelection([], null, 1)).toBeNull();
  });
});

describe("display text", () => {
  it("names MIDI notes with middle C as C4", () => {
    expect(midiNoteName(60)).toBe("C4");
    expect(midiNoteName(61)).toBe("C#4");
    expect(midiNoteName(21)).toBe("A0");
    expect(midiNoteName(108)).toBe("C8");
    expect(midiNoteName(0)).toBe("C-1");
  });
  it("formats times", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(75.4)).toBe("1:15");
    expect(formatTime(75.44, true)).toBe("1:15.4");
    expect(formatTime(5.06, true)).toBe("0:05.1");
    expect(formatTime(-3)).toBe("0:00");
  });
});

describe("pumpEvents (feeding the audio engine a little at a time)", () => {
  const hn = withHands(response.notes!, 480, 0, new Map(), {});
  it("hands over about a second ahead, timed relative to now", () => {
    const { events, until } = pumpEvents(hn, 0, 0, "both");
    expect(until).toBeCloseTo(1, 6);
    expect(events).toHaveLength(1);
    expect(events[0]!.start).toBe(0);
  });
  it("notes that start later are timed from the current play position", () => {
    // Bar 2 starts at 2.4 s. Standing at 1.6 s with the first second already handed over:
    const first = pumpEvents(hn, 0, 1.6, "both"); // covers up to 2.6 s, so includes bar 2's start
    expect(first.until).toBeCloseTo(2.6, 6);
    const startsFromNow = first.events.map((e) => e.start);
    expect(startsFromNow.some((s) => Math.abs(s - (2.4 - 1.6)) < 0.001)).toBe(true);
  });
  it("never hands the same note over twice", () => {
    const a = pumpEvents(hn, 0, 0.5, "both");
    const b = pumpEvents(hn, a.until, 1.0, "both");
    const all = [...a.events, ...b.events].flatMap((e) => e.notes);
    expect(all.length).toBe(new Set(hn.filter((n) => n.start_sec < b.until).map((n) => `${n.start_sec}:${n.midi}`)).size);
  });
  it("does nothing when already scheduled far enough ahead", () => {
    expect(pumpEvents(hn, 5, 1, "both")).toEqual({ events: [], until: 5 });
  });
  it("respects the hand filter", () => {
    const only = pumpEvents(hn, 0, 0, "L").events.flatMap((e) => e.notes);
    expect(only).toEqual([48]);
  });
});

describe("rateLimitAdvice", () => {
  it("retries after a pause the first couple of times, with a message that says why", () => {
    for (let i = 0; i < MAX_RATE_RETRIES; i++) {
      const a = rateLimitAdvice(i);
      expect(a.retry).toBe(true);
      expect(a.delayMs).toBeGreaterThan(1000);
      expect(a.message).toMatch(/short pause/);
    }
  });
  it("then stops, so it can never loop, and tells the person what to do", () => {
    const a = rateLimitAdvice(MAX_RATE_RETRIES);
    expect(a).toMatchObject({ retry: false, delayMs: 0 });
    expect(a.message).toMatch(/Wait a minute/);
    expect(rateLimitAdvice(99).retry).toBe(false);
  });
});
