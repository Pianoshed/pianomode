/**
 * What a saved MIDI project remembers, and how to put it back safely.
 *
 * The file itself is stored separately. This is everything the person changed in MIDI Studio.
 * Saved data is treated as untrusted when it comes back (a newer version of the app may have
 * written it, or it may be damaged): anything that does not fit is dropped and replaced by the
 * normal default, so a bad save can never stop a project from opening.
 */

import type { Grid, Hand, Prefer, TrackHandTag } from "@/lib/midi/api";
import type { ParsedMidi } from "@/lib/midi/smf";
import { type HandEdits, type TrackEdit, type TrackState, StudioError, applyTrackEdits, summarizeTracks, windowFrom } from "@/lib/midi/studio";

export const MIDI_PROJECT_VERSION = 1;

export type KeyChoice = { tonic: string; mode: string };
export type MidiProjectSettings = {
  edits: TrackEdit[];
  trackStates: Record<number, TrackState>;
  fromBar: number;
  grid: Grid;
  prefer: Prefer;
  keyChoice: KeyChoice | null;
  handEdits: Map<string, Hand>;
};

const HAND_TAGS: readonly TrackHandTag[] = ["L", "R", "both", "other"];
const MAX_HAND_EDITS = 20_000;

export function serializeMidiProject(s: {
  edits: readonly TrackEdit[];
  trackStates: Readonly<Record<number, TrackState>>;
  fromBar: number;
  grid: Grid;
  prefer: Prefer;
  keyChoice: KeyChoice | null;
  handEdits: HandEdits;
}): Record<string, unknown> {
  return {
    v: MIDI_PROJECT_VERSION,
    edits: s.edits,
    trackStates: s.trackStates,
    fromBar: s.fromBar,
    grid: s.grid,
    prefer: s.prefer,
    keyChoice: s.keyChoice,
    handEdits: [...s.handEdits.entries()],
  };
}

const isInt = (x: unknown, min: number, max: number): x is number => typeof x === "number" && Number.isInteger(x) && x >= min && x <= max;
const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

function readEdits(raw: unknown): TrackEdit[] {
  if (!Array.isArray(raw) || raw.length > 256) return [];
  const out: TrackEdit[] = [];
  for (const e of raw) {
    if (!isObj(e)) return [];
    if (e.type === "merge" && Array.isArray(e.from) && e.from.length <= 256 && e.from.every((n) => isInt(n, 0, 255)) && isInt(e.into, 0, 255)) {
      out.push({ type: "merge", from: e.from as number[], into: e.into });
    } else if (e.type === "split" && isInt(e.track, 0, 255) && isInt(e.pitch, 0, 127) && isInt(e.into, 0, 255)) {
      out.push({ type: "split", track: e.track, pitch: e.pitch, into: e.into });
    } else return []; // one bad edit and the list may no longer make sense: start from the file as it was
  }
  return out;
}

/** Settings for `parsed`, from whatever was saved. Never throws. */
export function restoreMidiProject(saved: unknown, parsed: ParsedMidi): MidiProjectSettings {
  const data = isObj(saved) ? saved : {};

  let edits = readEdits(data.edits);
  try {
    applyTrackEdits(parsed.notes, edits);
  } catch {
    edits = []; // the edits do not fit this file
  }

  // Every track that has notes gets a state; saved ones are used where they are valid.
  const savedStates = isObj(data.trackStates) ? data.trackStates : {};
  const trackStates: Record<number, TrackState> = {};
  for (const t of summarizeTracks(parsed, edits)) {
    const s = savedStates[String(t.index)];
    const ok = isObj(s);
    trackStates[t.index] = {
      hand: ok && HAND_TAGS.includes(s.hand as TrackHandTag) ? (s.hand as TrackHandTag) : null,
      muted: ok && typeof s.muted === "boolean" ? s.muted : t.drumsOnly,
      solo: ok && typeof s.solo === "boolean" ? s.solo : false,
    };
  }

  let fromBar = isInt(data.fromBar, 0, 100_000) ? data.fromBar : 0;
  try {
    windowFrom(parsed, fromBar);
  } catch (e) {
    if (!(e instanceof StudioError)) throw e;
    fromBar = 0;
  }

  const kc = data.keyChoice;
  const keyChoice =
    isObj(kc) && typeof kc.tonic === "string" && /^[A-G][b#]?$/.test(kc.tonic) && (kc.mode === "major" || kc.mode === "minor")
      ? { tonic: kc.tonic, mode: kc.mode }
      : null;

  const handEdits = new Map<string, Hand>();
  if (Array.isArray(data.handEdits)) {
    for (const pair of data.handEdits.slice(0, MAX_HAND_EDITS)) {
      if (Array.isArray(pair) && typeof pair[0] === "string" && pair[0].length <= 40 && (pair[1] === "L" || pair[1] === "R")) {
        handEdits.set(pair[0], pair[1]);
      }
    }
  }

  return {
    edits,
    trackStates,
    fromBar,
    grid: data.grid === "half_bar" || data.grid === "bar" ? data.grid : "beat",
    prefer: data.prefer === "flats" ? "flats" : "sharps",
    keyChoice,
    handEdits,
  };
}
