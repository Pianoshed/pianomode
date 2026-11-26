/** Pure logic for MIDI Studio: no React, no network, no clock. */

import type { ScheduledEvent } from "@/lib/piano/audio";
import { type Mark, type Overlay, overlayFromCandidate } from "@/lib/piano/highlight";
import type { AnalyzeRequest, AnalyzeResponse, Hand, MidiEventIn, NoteOut, Segment, TrackHandTag } from "./api";
import type { MidiNote, ParsedMidi, TimeSignature } from "./smf";

/** The analysis service accepts 20,000 events (a note is two). */
export const MAX_EVENTS = 20_000;
export const MAX_NOTES_PER_WINDOW = MAX_EVENTS / 2;
export const MAX_TRACK_ID = 255;

// ------------------------------------------------------------------ track edits

export type TrackEdit =
  | { type: "merge"; from: number[]; into: number }
  | { type: "split"; track: number; pitch: number; into: number };

export class StudioError extends Error {
  constructor(
    public code: "track_in_use" | "bad_edit" | "too_dense" | "too_many_events",
    message: string,
  ) {
    super(message);
    this.name = "StudioError";
  }
}

/** The notes with each edit applied in order. Merging moves whole tracks onto one; splitting moves
 *  the notes at or above a pitch to a track that must not already have notes. Nothing is lost. */
export function applyTrackEdits(notes: readonly MidiNote[], edits: readonly TrackEdit[]): MidiNote[] {
  let out = notes.map((n) => ({ ...n }));
  for (const e of edits) {
    if (e.type === "merge") {
      if (e.from.includes(e.into)) throw new StudioError("bad_edit", "A track cannot be merged into itself.");
      const from = new Set(e.from);
      out = out.map((n) => (from.has(n.track) ? { ...n, track: e.into } : n));
    } else {
      if (e.into !== e.track && out.some((n) => n.track === e.into)) throw new StudioError("track_in_use", `Track ${e.into + 1} already has notes.`);
      out = out.map((n) => (n.track === e.track && n.note >= e.pitch ? { ...n, track: e.into } : n));
    }
  }
  return out;
}

export type TrackSummary = { index: number; name: string; noteCount: number; lowest: number | null; highest: number | null; drumsOnly: boolean; derived: boolean };

/** One row per track that has notes after the edits. Original names are kept; a track created or
 *  absorbing others by an edit says so. */
export function summarizeTracks(parsed: ParsedMidi, edits: readonly TrackEdit[]): TrackSummary[] {
  const notes = applyTrackEdits(parsed.notes, edits);
  const original = new Map(parsed.tracks.map((t) => [t.index, t]));
  const splitFrom = new Map(edits.flatMap((e) => (e.type === "split" ? [[e.into, e.track] as const] : [])));
  const merged = new Set(edits.flatMap((e) => (e.type === "merge" ? [e.into] : [])));
  const byTrack = new Map<number, MidiNote[]>();
  for (const n of notes) byTrack.set(n.track, [...(byTrack.get(n.track) ?? []), n]);
  return [...byTrack.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([index, ns]) => {
      const o = original.get(index);
      const pitches = ns.map((n) => n.note);
      const base = o?.name ?? `Track ${index + 1}`;
      const source = splitFrom.has(index) ? original.get(splitFrom.get(index) as number) : undefined;
      const name = splitFrom.has(index) ? `${source?.name ?? `Track ${(splitFrom.get(index) as number) + 1}`} (upper part)` : merged.has(index) ? `${base} (merged)` : base;
      const drums = ns.every((n) => n.channel === 9);
      return { index, name, noteCount: ns.length, lowest: Math.min(...pitches), highest: Math.max(...pitches), drumsOnly: drums, derived: splitFrom.has(index) || merged.has(index) };
    });
}

/** A free track number for a split, or null if all 256 are used. */
export function freeTrack(parsed: ParsedMidi, edits: readonly TrackEdit[]): number | null {
  const used = new Set(applyTrackEdits(parsed.notes, edits).map((n) => n.track));
  for (let i = 0; i <= MAX_TRACK_ID; i++) if (!used.has(i) && !edits.some((e) => e.type === "split" && e.into === i)) return i;
  return null;
}

// ------------------------------------------------------------------ bars and windows

const ticksPerBar = (ppq: number, ts: Pick<TimeSignature, "numerator" | "denominator">): number => Math.round((ppq * 4 * ts.numerator) / ts.denominator);

/** Start tick of every bar up to the end of the music. A time signature takes effect at its tick
 *  (normally a barline); with none given the music is in 4/4. */
export function barStarts(ppq: number, timeSignatures: readonly TimeSignature[], endTick: number): number[] {
  const sigs = [...timeSignatures].sort((a, b) => a.tick - b.tick);
  let current = { numerator: 4, denominator: 4 };
  let next = 0;
  const starts: number[] = [];
  let tick = 0;
  while (tick < Math.max(endTick, 1)) {
    while (next < sigs.length && sigs[next]!.tick <= tick) current = sigs[next++]!;
    starts.push(tick);
    tick += ticksPerBar(ppq, current);
  }
  return starts;
}

export type Window = {
  fromBar: number; // 0-based, inclusive
  toBar: number; // exclusive
  totalBars: number;
  startTick: number;
  endTick: number; // Infinity for the window that reaches the end
  noteCount: number;
  whole: boolean;
};

const count = (notes: readonly MidiNote[], from: number, to: number): number => notes.filter((n) => n.startTick >= from && n.startTick < to).length;

/** The widest run of bars from `fromBar` whose notes fit one analysis request. */
export function windowFrom(parsed: Pick<ParsedMidi, "ppq" | "timeSignatures" | "endTick" | "notes">, fromBar: number, maxNotes = MAX_NOTES_PER_WINDOW): Window {
  const starts = barStarts(parsed.ppq, parsed.timeSignatures, parsed.endTick);
  const total = starts.length;
  const from = Math.min(Math.max(0, fromBar), total - 1);
  const tickAt = (bar: number) => (bar >= total ? Infinity : (starts[bar] as number));
  let to = from;
  let n = 0;
  while (to < total) {
    const here = count(parsed.notes, tickAt(to), tickAt(to + 1));
    if (n + here > maxNotes) break;
    n += here;
    to++;
  }
  if (to === from) throw new StudioError("too_dense", `Bar ${from + 1} alone has more than ${maxNotes.toLocaleString()} notes, which is more than can be analysed at once.`);
  return { fromBar: from, toBar: to, totalBars: total, startTick: tickAt(from), endTick: tickAt(to), noteCount: n, whole: from === 0 && to === total };
}

/** The window that follows (or precedes) this one, as wide as it can be. */
export function neighbour(parsed: Parameters<typeof windowFrom>[0], w: Window, direction: 1 | -1, maxNotes = MAX_NOTES_PER_WINDOW): Window | null {
  if (direction === 1) return w.toBar >= w.totalBars ? null : windowFrom(parsed, w.toBar, maxNotes);
  if (w.fromBar === 0) return null;
  // Walk back to the earliest start whose window still ends at or before this one begins.
  for (let from = 0; from < w.fromBar; from++) {
    const c = windowFrom(parsed, from, maxNotes);
    if (c.toBar >= w.fromBar) return { ...c, toBar: w.fromBar, endTick: barStarts(parsed.ppq, parsed.timeSignatures, parsed.endTick)[w.fromBar] as number, whole: false };
  }
  return null;
}

// ------------------------------------------------------------------ the analysis request

export type TrackState = { hand: TrackHandTag | null; muted: boolean; solo: boolean };
export type RequestOptions = { grid: AnalyzeRequest["grid"]; prefer: AnalyzeRequest["prefer"]; key: { tonic: string; mode: string } | null; trackStates: Readonly<Record<number, TrackState>>; trackNames?: Readonly<Record<number, string>> };

const inEffect = <T extends { tick: number }>(items: readonly T[], tick: number): T | undefined => [...items].filter((i) => i.tick <= tick).sort((a, b) => a.tick - b.tick).at(-1);

/** Note events for one window, shifted so the window starts at tick 0. The tempo and time
 *  signature in effect at the window's start become the new tick-0 values. A note that runs past
 *  the end of a partial window is cut at its end so it cannot leak into the next section. */
export function buildAnalyzeRequest(parsed: ParsedMidi, notes: readonly MidiNote[], w: Window, o: RequestOptions): AnalyzeRequest {
  const inside = notes.filter((n) => n.startTick >= w.startTick && n.startTick < w.endTick);
  const events: MidiEventIn[] = [];
  for (const n of inside) {
    const end = Math.min(n.endTick, w.endTick);
    if (end <= n.startTick) continue;
    events.push({ tick: n.startTick - w.startTick, kind: "note_on", note: n.note, velocity: n.velocity, channel: n.channel, track: n.track });
    events.push({ tick: end - w.startTick, kind: "note_off", note: n.note, velocity: 0, channel: n.channel, track: n.track });
  }
  if (events.length > MAX_EVENTS) throw new StudioError("too_many_events", "That section has too many notes to analyse at once.");

  const tempo = parsed.tempoChanges;
  const startTempo = inEffect(tempo, w.startTick);
  const tempoChanges = [...(startTempo ? [{ tick: 0, bpm: startTempo.bpm }] : []), ...tempo.filter((t) => t.tick > w.startTick && t.tick < w.endTick).map((t) => ({ tick: t.tick - w.startTick, bpm: t.bpm }))];
  const sigs = parsed.timeSignatures;
  const startSig = inEffect(sigs, w.startTick);
  const timeSignatures = [...(startSig ? [{ tick: 0, numerator: startSig.numerator, denominator: startSig.denominator }] : []), ...sigs.filter((t) => t.tick > w.startTick && t.tick < w.endTick).map((t) => ({ tick: t.tick - w.startTick, numerator: t.numerator, denominator: t.denominator }))];

  const used = [...new Set(inside.map((n) => n.track))].sort((a, b) => a - b);
  return {
    ppq: parsed.ppq,
    events,
    tempo_changes: tempoChanges,
    time_signatures: timeSignatures,
    key: o.key,
    grid: o.grid,
    prefer: o.prefer,
    track_states: used.map((t) => ({ track: t, name: o.trackNames?.[t] ?? null, hand: o.trackStates[t]?.hand ?? null, muted: o.trackStates[t]?.muted ?? false, solo: o.trackStates[t]?.solo ?? false })),
    max_candidates: 3,
    include_notes: true,
  };
}

// ------------------------------------------------------------------ hands

export type HandSource = "auto" | "track" | "user";
export type HandNote = NoteOut & { hand: Hand | null; handSource: HandSource | null; key: string };
export type HandEdits = ReadonlyMap<string, Hand>;

/** A note's identity that survives re-analysis: where it starts, its pitch and channel. (The
 *  service's note ids are positions in a sorted list and change when the section or tracks do.) */
export const noteKey = (tick: number, midi: number, channel: number): string => `${tick}:${midi}:${channel}`;

/** Server suggestions with a person's decisions on top: a note edited by hand wins; otherwise a
 *  track assigned to one hand sets its notes; otherwise the service's suggestion stands. */
export function withHands(notes: readonly NoteOut[], ppq: number, windowStartTick: number, edits: HandEdits, trackHands: Readonly<Record<number, TrackHandTag | null>>): HandNote[] {
  return notes.map((n) => {
    const key = noteKey(Math.round(n.start_beat * ppq) + windowStartTick, n.midi, n.channel);
    const edited = edits.get(key);
    if (edited) return { ...n, key, hand: edited, handSource: "user" as const };
    const tag = trackHands[n.track];
    if (tag === "L" || tag === "R") return { ...n, key, hand: tag, handSource: "track" as const };
    return { ...n, key, hand: n.hand, handSource: n.hand ? ("auto" as const) : null };
  });
}

export const flipHand = (h: Hand | null): Hand => (h === "L" ? "R" : "L");

// ------------------------------------------------------------------ playback

export type HandFilter = "both" | Hand;

/** Notes that sound in [from, to) seconds: those that start in the span (the caller schedules
 *  these ahead), restricted to the chosen hand. Times are relative to `from`; the beat unit is a
 *  second because playback runs at 60 beats per minute. */
export function eventsBetween(notes: readonly HandNote[], from: number, to: number, only: HandFilter): ScheduledEvent[] {
  const groups = new Map<string, { notes: number[]; start: number; duration: number }>();
  for (const n of notes) {
    if (n.start_sec < from || n.start_sec >= to) continue;
    if (only !== "both" && n.hand !== only) continue;
    const start = n.start_sec - from;
    const duration = Math.max(0.05, n.end_sec - n.start_sec);
    const key = `${start.toFixed(4)}:${duration.toFixed(4)}`;
    const g = groups.get(key) ?? { notes: [], start, duration };
    g.notes.push(n.midi);
    groups.set(key, g);
  }
  return [...groups.values()].sort((a, b) => a.start - b.start);
}

export const notesSounding = (notes: readonly HandNote[], sec: number): HandNote[] => notes.filter((n) => n.start_sec <= sec && sec < n.end_sec);

export function segmentAt(segments: readonly Segment[], sec: number): Segment | null {
  return segments.find((s) => s.start_sec <= sec && sec < s.end_sec) ?? null;
}

export const totalSeconds = (r: Pick<AnalyzeResponse, "segments" | "notes">): number => Math.max(0, ...(r.notes ?? []).map((n) => n.end_sec), ...r.segments.map((s) => s.end_sec));

// ------------------------------------------------------------------ chord display

export type SegmentLook = { label: string; sublabel: string | null; kind: "identified" | "ambiguous" | "unknown" | "silence" };
/** What a timeline cell says. An ambiguous reading is marked as such rather than shown as fact. */
export function segmentLook(s: Segment): SegmentLook {
  const top = s.candidates[0];
  if (s.status === "silence") return { label: "", sublabel: null, kind: "silence" };
  if (s.status === "no_reliable_label" || !top) return { label: "?", sublabel: null, kind: "unknown" };
  const numeral = s.numeral?.figure ?? null; // the Roman numeral, e.g. vi or V7 (not the chord name)
  return { label: s.status === "ambiguous" ? `${top.symbol}?` : top.symbol, sublabel: numeral, kind: s.status === "ambiguous" ? "ambiguous" : "identified" };
}

/** Keyboard marks for the notes sounding now. When a chord reading exists the notes are coloured
 *  as that reading's root, tones and extras; either way each note shows which hand plays it. */
export function overlayForMoment(sounding: readonly HandNote[], segment: Segment | null): Overlay | null {
  if (sounding.length === 0) return null;
  const midis = [...new Set(sounding.map((n) => n.midi))].sort((a, b) => a - b);
  const top = segment?.candidates[0];
  const base: Overlay = top && segment?.status !== "silence" ? overlayFromCandidate(top, midis) : { source: "identify", title: "", marks: new Map(), spelling: {} };
  const marks = new Map<number, Mark>(base.marks);
  const lowest = midis[0];
  for (const n of sounding) {
    const existing = marks.get(n.midi);
    marks.set(n.midi, { role: existing?.role ?? "tone", label: existing?.label || n.name.replace(/\d+$/, ""), hand: n.hand ?? undefined, bass: n.midi === lowest });
  }
  return { ...base, title: top && segment?.status !== "silence" ? top.symbol : "", marks };
}

// ------------------------------------------------------------------ piano roll

export type RollView = { duration: number; pxPerSec: number; lo: number; hi: number; rowH: number; left: number; top: number };
export const rollX = (v: RollView, sec: number): number => v.left + sec * v.pxPerSec;
export const rollY = (v: RollView, midi: number): number => v.top + (v.hi - midi) * v.rowH;
export const rollWidth = (v: RollView): number => v.left + Math.max(1, v.duration) * v.pxPerSec + 8;
export const rollHeight = (v: RollView): number => v.top + (v.hi - v.lo + 1) * v.rowH + 4;

export function makeRollView(notes: readonly Pick<NoteOut, "midi">[], duration: number, pxPerSec: number, rowH = 8): RollView {
  const pitches = notes.map((n) => n.midi);
  let lo = pitches.length ? Math.min(...pitches) - 1 : 48;
  let hi = pitches.length ? Math.max(...pitches) + 1 : 72;
  while (hi - lo < 23) {
    hi++;
    if (hi - lo < 23) lo--;
  }
  return { duration, pxPerSec, lo: Math.max(0, lo), hi: Math.min(127, hi), rowH, left: 28, top: 4 };
}

/** The note under a point, topmost (latest drawn) first. */
export function noteAtPoint<T extends Pick<NoteOut, "midi" | "start_sec" | "end_sec">>(notes: readonly T[], v: RollView, x: number, y: number): T | null {
  for (let i = notes.length - 1; i >= 0; i--) {
    const n = notes[i] as T;
    const nx = rollX(v, n.start_sec);
    const w = Math.max(3, (n.end_sec - n.start_sec) * v.pxPerSec);
    const ny = rollY(v, n.midi);
    if (x >= nx && x <= nx + w && y >= ny && y < ny + v.rowH) return n;
  }
  return null;
}

export const secondsAtX = (v: RollView, x: number): number => Math.min(v.duration, Math.max(0, (x - v.left) / v.pxPerSec));

/** The next or previous note in time order, for keyboard navigation of the roll. */
export function stepSelection<T extends { start_sec: number; midi: number }>(notes: readonly T[], current: T | null, direction: 1 | -1): T | null {
  if (notes.length === 0) return null;
  if (!current) return direction === 1 ? (notes[0] as T) : (notes.at(-1) as T);
  const i = notes.indexOf(current);
  return notes[Math.min(notes.length - 1, Math.max(0, i + direction))] as T;
}

// ------------------------------------------------------------------ display text

const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
/** "C4" for MIDI 60 (middle C is C4), using sharps. Display only: the service spells notes. */
export const midiNoteName = (midi: number): string => `${NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;

/** Seconds as m:ss, or m:ss.s when `tenths` is set. */
export function formatTime(sec: number, tenths = false): string {
  const t = Math.max(0, sec);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return tenths ? `${m}:${s.toFixed(1).padStart(4, "0")}` : `${m}:${String(Math.floor(s)).padStart(2, "0")}`;
}

/** How far ahead of "now" notes are handed to the audio engine, and how often. The engine caps
 *  the number of voices when notes are *scheduled*, so scheduling far ahead would cut notes off. */
export const LOOKAHEAD_SEC = 1.0;
export const PUMP_MS = 250;
/** The audio engine starts a scheduled note this long after it is asked to (see PianoAudio). */
export const AUDIO_LATENCY_SEC = 0.06;

/** Notes to hand over at one pump: those starting in [scheduledUntil, playTime + LOOKAHEAD),
 *  timed relative to *now* (playTime), which is what the audio engine expects. */
export function pumpEvents(notes: readonly HandNote[], scheduledUntil: number, playTime: number, only: HandFilter): { events: ScheduledEvent[]; until: number } {
  const until = playTime + LOOKAHEAD_SEC;
  if (until <= scheduledUntil) return { events: [], until: scheduledUntil };
  const shift = scheduledUntil - playTime;
  const events = eventsBetween(notes, scheduledUntil, until, only).map((e) => ({ ...e, start: e.start + shift }));
  return { events, until };
}

// ------------------------------------------------------------------ when the server asks for a pause

export const MAX_RATE_RETRIES = 2;
export const RATE_RETRY_MS = 6000;
export type RateAdvice = { retry: boolean; delayMs: number; message: string };
/** What to do after a "slow down" reply. The Studio asks again on every change, so a quick run of
 *  changes can reach the limit; it waits and retries a couple of times, then stops and says so. */
export function rateLimitAdvice(retriesSoFar: number): RateAdvice {
  if (retriesSoFar < MAX_RATE_RETRIES) {
    return { retry: true, delayMs: RATE_RETRY_MS, message: "You are changing things quickly, so the server asked for a short pause. Trying again in a few seconds…" };
  }
  return { retry: false, delayMs: 0, message: "Too many changes in a short time. Wait a minute, then change any setting to analyse again." };
}
