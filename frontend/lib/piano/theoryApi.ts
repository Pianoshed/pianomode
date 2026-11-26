/** Typed calls to the music-theory API. The piano never works out theory itself: names, spellings,
 *  chord tones, scales and chord identification all come from these endpoints. Types here cover only
 *  the fields the piano uses; `__fixtures__` holds real responses that the tests check them against. */

import { type ApiResult, api } from "@/lib/api";

const BASE = "/api/v1/theory";

export type NoteOut = {
  name: string;
  name_unicode: string;
  octave: number | null;
  midi: number | null;
  pitch_class: number;
  frequency: number | null;
};
export type ChordTone = { name: string; interval: string; degree: number };
export type ChordOut = {
  symbol: string;
  root: string;
  type_id: string;
  quality: string;
  bass: string;
  inversion: number | null;
  inversion_name: string | null;
  tones: ChordTone[];
  pitch_classes: number[];
};
export type ChordConstruct = { chord: ChordOut; notes: NoteOut[]; midi_notes: number[]; aliases: string[] };

export type Candidate = {
  symbol: string;
  root: string;
  type_id: string;
  quality: string;
  score: number;
  required_tones: string[];
  detected_tones: string[];
  missing_tones: string[];
  extra_tones: string[];
  bass: string;
  inversion: number | null;
  inversion_name: string | null;
  rootless: boolean;
  added_tones: string[];
  altered_tones: string[];
  enharmonic_symbol: string | null;
  assumptions: string[];
};
export type ChordIdentify = {
  status: "identified" | "ambiguous" | "no_reliable_label";
  reason: string | null;
  bass: string | null;
  pitch_classes: number[];
  candidates: Candidate[];
  score_meaning: string;
};

export type ScaleInfo = {
  id: string;
  name: string;
  family: string;
  size: number;
  formula: string[];
  aliases: string[];
  /** False for administrator-defined scales. */
  builtin?: boolean;
};
export type ScaleResult = {
  root: string;
  scale: ScaleInfo;
  direction: string;
  notes: string[];
  degrees: { number: number; note: string; interval: string }[];
  keyboard: NoteOut[];
  /** Curated one-octave fingering (finger 1 = thumb), or null when none is curated. */
  fingering?: { right_hand: number[]; left_hand: number[]; direction: string; note: string } | null;
};

export type ChordTypeInfo = {
  id: string;
  name: string;
  symbol: string;
  family: string;
  formula: string[];
  aliases: string[];
};

export type VoicingOut = { left: number[]; right: number[]; left_names: string[]; right_names: string[] };
export type VoicingsResult = {
  chord: ChordOut;
  total_found: number;
  returned: number;
  voicings: { voicing: VoicingOut }[];
  message: string | null;
};

const post = <T>(path: string, body: unknown): Promise<ApiResult<T>> => api<T>(`${BASE}${path}`, { method: "POST", body });

export type ChordRequest =
  | { symbol: string; octave?: number; inversion?: number }
  | { root: string; type: string; octave?: number; inversion?: number; bass?: string };

export const constructChord = (req: ChordRequest) => post<ChordConstruct>("/chords/construct", req);

export const identifyChord = (midi: number[], opts: { prefer: "sharps" | "flats"; allowRootless?: boolean }) =>
  post<ChordIdentify>("/chords/identify", {
    notes: midi,
    prefer: opts.prefer,
    allow_rootless: opts.allowRootless ?? false,
    max_candidates: 5,
  });

export const generateScale = (root: string, scale: string, octave = 4) =>
  post<ScaleResult>("/scales/generate", { root, scale, octave });

export const generateVoicings = (symbol: string, skill: "beginner" | "intermediate" | "advanced" | "expert") =>
  post<VoicingsResult>("/voicings/generate", { chord: symbol, limit: 1, config: { skill } });

// The two catalogues never change while the page is open, so fetch each once.
let chordTypes: Promise<ApiResult<{ types: ChordTypeInfo[] }>> | null = null;
let scales: Promise<ApiResult<{ scales: ScaleInfo[] }>> | null = null;

export function listChordTypes() {
  chordTypes ??= api<{ types: ChordTypeInfo[] }>(`${BASE}/chords/types`);
  return chordTypes.then((r) => {
    if (!r.ok) chordTypes = null; // let a later call retry after a failure
    return r;
  });
}
export function listScales() {
  scales ??= api<{ scales: ScaleInfo[] }>(`${BASE}/scales`);
  return scales.then((r) => {
    if (!r.ok) scales = null;
    return r;
  });
}

/** Test hook: forget cached catalogues. */
export function resetCatalogueCache(): void {
  chordTypes = null;
  scales = null;
}
