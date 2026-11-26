/** Turns what a person has done in MIDI Studio into notes ready to write as a MIDI file, and saves
 *  or restores those corrections as a small file. Pure: no React, no network. */

import type { Grid, Hand, Prefer, TrackHandTag } from "./api";
import { type TrackEdit, type TrackState, applyTrackEdits, noteKey } from "./studio";
import type { MidiNote, ParsedMidi } from "./smf";
import type { OutTrack } from "./writer";

const HAND_WORD: Partial<Record<TrackHandTag, string>> = { L: "left hand", R: "right hand" };

/** Tracks to write: every track that has notes after the person's merges and splits, named with
 *  the hand it was assigned to, with per-note hand corrections gathered into two extra tracks.
 *  Muted tracks are left out (and, when any track is soloed, everything else is), so the file
 *  sounds like what the person heard. */
export function exportTracks(
  parsed: ParsedMidi,
  edits: readonly TrackEdit[],
  states: Readonly<Record<number, TrackState>>,
  handEdits: ReadonlyMap<string, Hand>,
  includeMuted = false,
): OutTrack[] {
  const notes = applyTrackEdits(parsed.notes, edits);
  const anySolo = Object.values(states).some((s) => s.solo);
  const audible = (t: number): boolean => {
    const s = states[t];
    if (includeMuted || !s) return true;
    return anySolo ? s.solo : !s.muted;
  };
  const byTrack = new Map<number, MidiNote[]>();
  const corrected: Record<Hand, MidiNote[]> = { L: [], R: [] };
  for (const n of notes) {
    if (!audible(n.track)) continue;
    const hand = handEdits.get(noteKey(n.startTick, n.note, n.channel));
    if (hand) corrected[hand].push(n);
    else byTrack.set(n.track, [...(byTrack.get(n.track) ?? []), n]);
  }
  const out: OutTrack[] = [];
  for (const index of [...byTrack.keys()].sort((a, b) => a - b)) {
    const base = parsed.tracks.find((t) => t.index === index)?.name?.trim() || `Track ${index + 1}`;
    const word = states[index]?.hand ? HAND_WORD[states[index]?.hand as TrackHandTag] : undefined;
    out.push({ name: word ? `${base} (${word})` : base, notes: byTrack.get(index) as MidiNote[] });
  }
  if (corrected.L.length) out.push({ name: "Left hand (corrected)", notes: corrected.L });
  if (corrected.R.length) out.push({ name: "Right hand (corrected)", notes: corrected.R });
  return out;
}

// ------------------------------------------------------------------ saving corrections

export const CORRECTIONS_VERSION = 1;
export const MAX_CORRECTIONS_BYTES = 1_000_000;
const TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const GRIDS: readonly string[] = ["beat", "half_bar", "bar"];
const PREFERS: readonly string[] = ["sharps", "flats"];

export type Corrections = {
  version: number;
  file: { name: string | null; ppq: number; noteCount: number };
  edits: TrackEdit[];
  trackStates: Record<number, TrackState>;
  handEdits: [string, Hand][];
  key: { tonic: string; mode: string } | null;
  grid: Grid;
  prefer: Prefer;
};

export type CorrectionsInput = {
  fileName: string | null;
  parsed: ParsedMidi;
  edits: readonly TrackEdit[];
  trackStates: Readonly<Record<number, TrackState>>;
  handEdits: ReadonlyMap<string, Hand>;
  key: { tonic: string; mode: string } | null;
  grid: Grid;
  prefer: Prefer;
};

export function corrections(i: CorrectionsInput): Corrections {
  return {
    version: CORRECTIONS_VERSION,
    file: { name: i.fileName, ppq: i.parsed.ppq, noteCount: i.parsed.notes.length },
    edits: [...i.edits],
    trackStates: { ...i.trackStates },
    handEdits: [...i.handEdits.entries()],
    key: i.key,
    grid: i.grid,
    prefer: i.prefer,
  };
}

const isInt = (v: unknown, lo: number, hi: number): v is number => typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export type CorrectionsResult = { ok: true; data: Corrections } | { ok: false; error: string };

/** Read a corrections file, checking every field and that it was saved for this MIDI file.
 *  Nothing from the file is trusted: shapes, ranges and sizes are all checked. */
export function parseCorrections(text: string, parsed: ParsedMidi): CorrectionsResult {
  const bad = (error: string): CorrectionsResult => ({ ok: false, error });
  if (text.length > MAX_CORRECTIONS_BYTES) return bad("That corrections file is too large.");
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return bad("That is not a corrections file (it could not be read as JSON).");
  }
  if (!isRecord(raw) || raw.version !== CORRECTIONS_VERSION) return bad("That corrections file is from a different version.");
  const file = raw.file;
  if (!isRecord(file) || file.ppq !== parsed.ppq || file.noteCount !== parsed.notes.length) return bad("These corrections were saved for a different MIDI file.");

  if (!Array.isArray(raw.edits) || raw.edits.length > 500) return bad("The track edits are not valid.");
  const edits: TrackEdit[] = [];
  for (const e of raw.edits) {
    if (!isRecord(e)) return bad("The track edits are not valid.");
    if (e.type === "merge" && Array.isArray(e.from) && e.from.length <= 255 && e.from.every((t) => isInt(t, 0, 255)) && isInt(e.into, 0, 255)) edits.push({ type: "merge", from: e.from as number[], into: e.into });
    else if (e.type === "split" && isInt(e.track, 0, 255) && isInt(e.pitch, 0, 127) && isInt(e.into, 0, 255)) edits.push({ type: "split", track: e.track, pitch: e.pitch, into: e.into });
    else return bad("The track edits are not valid.");
  }

  if (!isRecord(raw.trackStates)) return bad("The track settings are not valid.");
  const trackStates: Record<number, TrackState> = {};
  for (const [k, v] of Object.entries(raw.trackStates)) {
    const t = Number(k);
    if (!isInt(t, 0, 255) || !isRecord(v) || typeof v.muted !== "boolean" || typeof v.solo !== "boolean") return bad("The track settings are not valid.");
    if (v.hand !== null && !["L", "R", "both", "other"].includes(v.hand as string)) return bad("The track settings are not valid.");
    trackStates[t] = { hand: v.hand as TrackHandTag | null, muted: v.muted, solo: v.solo };
  }

  if (!Array.isArray(raw.handEdits) || raw.handEdits.length > 20_000) return bad("The hand corrections are not valid.");
  const handEdits: [string, Hand][] = [];
  for (const h of raw.handEdits) {
    if (!Array.isArray(h) || h.length !== 2 || typeof h[0] !== "string" || !/^\d{1,10}:\d{1,3}:\d{1,2}$/.test(h[0]) || (h[1] !== "L" && h[1] !== "R")) return bad("The hand corrections are not valid.");
    handEdits.push([h[0], h[1]]);
  }

  let key: Corrections["key"] = null;
  if (raw.key !== null) {
    if (!isRecord(raw.key) || !TONICS.includes(raw.key.tonic as string) || (raw.key.mode !== "major" && raw.key.mode !== "minor")) return bad("The key is not valid.");
    key = { tonic: raw.key.tonic as string, mode: raw.key.mode };
  }
  if (!GRIDS.includes(raw.grid as string) || !PREFERS.includes(raw.prefer as string)) return bad("The analysis settings are not valid.");

  return { ok: true, data: { version: CORRECTIONS_VERSION, file: { name: typeof file.name === "string" ? file.name.slice(0, 200) : null, ppq: parsed.ppq, noteCount: parsed.notes.length }, edits, trackStates, handEdits, key, grid: raw.grid as Grid, prefer: raw.prefer as Prefer } };
}
