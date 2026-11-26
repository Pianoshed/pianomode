/** From chroma to chord regions: template matching, a "no chord" state, Viterbi smoothing, and
 *  merging into regions. This is a small, transparent estimator, not a trained model.
 *
 *  What a region's `scores` are: the average cosine similarity between the audio's chroma and
 *  each chord template. They rank candidates against each other. They are NOT probabilities and
 *  are never presented as such; no calibration has been done. */

import { type ChromaTrack, frameTime } from "./chroma";

export const QUALITIES = ["maj", "min", "7", "maj7", "min7"] as const;
export type Quality = (typeof QUALITIES)[number];
export type ChordSet = "triads" | "sevenths";
export const CHORD_SETS: Record<ChordSet, readonly Quality[]> = { triads: ["maj", "min"], sevenths: QUALITIES };
export const PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] as const;
export const NO_CHORD = "N";

/** Weights of the chord's tones, as semitones above the root. */
const SHAPES: Record<Quality, readonly (readonly [number, number])[]> = {
  maj: [[0, 1], [4, 0.9], [7, 0.85]],
  min: [[0, 1], [3, 0.9], [7, 0.85]],
  "7": [[0, 1], [4, 0.9], [7, 0.85], [10, 0.7]],
  maj7: [[0, 1], [4, 0.9], [7, 0.85], [11, 0.7]],
  min7: [[0, 1], [3, 0.9], [7, 0.85], [10, 0.7]],
};

export type Template = { label: string; root: number; quality: Quality; vec: Float32Array };

export function buildTemplates(set: ChordSet): Template[] {
  const out: Template[] = [];
  for (let root = 0; root < 12; root++) {
    for (const quality of CHORD_SETS[set]) {
      const vec = new Float32Array(12);
      for (const [semis, w] of SHAPES[quality]) vec[(root + semis) % 12] = w;
      const norm = Math.hypot(...vec);
      for (let i = 0; i < 12; i++) vec[i] = (vec[i] as number) / norm;
      out.push({ label: `${PITCH_NAMES[root]}:${quality}`, root, quality, vec });
    }
  }
  return out;
}

/** Cosine similarity of a chroma frame with every template (0 for an empty frame). */
export function scoreFrame(chroma: Float32Array, templates: readonly Template[], out: Float32Array): void {
  let norm = 0;
  for (let i = 0; i < 12; i++) norm += (chroma[i] as number) ** 2;
  norm = Math.sqrt(norm);
  if (norm === 0) {
    out.fill(0);
    return;
  }
  templates.forEach((t, k) => {
    let dot = 0;
    for (let i = 0; i < 12; i++) dot += (chroma[i] as number) * (t.vec[i] as number);
    out[k] = dot / norm;
  });
}

/** How strongly a frame favours a few pitch classes: 1 for a flat spread, about 4 for a triad. */
export function peakiness(chroma: Float32Array): number {
  let sum = 0;
  let max = 0;
  for (let i = 0; i < 12; i++) {
    const v = chroma[i] as number;
    sum += v;
    if (v > max) max = v;
  }
  return sum === 0 ? 0 : (max * 12) / sum;
}

const percentile = (values: ArrayLike<number>, p: number): number => {
  const sorted = Array.from(values).sort((a, b) => a - b);
  return sorted.length ? (sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] as number) : 0;
};

/** How well "no chord" explains a frame: 1 for near-silence, high for a flat (noise-like) spread,
 *  low for a frame with clear pitches. */
export function noChordScore(chroma: Float32Array, rms: number, loudRms: number): number {
  if (rms < Math.max(1e-4, 0.03 * loudRms)) return 1;
  const flat = Math.min(1, Math.max(0, (2.0 - peakiness(chroma)) / 0.7));
  return 0.85 * flat;
}

/** A pitch class counts as evidence for a region when its average energy is at least this fraction
 *  of the strongest. Measured on clean synthesised chords: every genuine chord tone is at least
 *  0.35 and no other pitch class is above 0.13, so 0.25 sits in the gap. Noisier audio will blur
 *  that gap, which is what the server's check of the label against this evidence is for. */
export const PITCH_EVIDENCE_RATIO = 0.25;

const ALPHA = 10;
/** Cost of changing chord, in the same units as the evidence (10 x similarity per frame). */
export const switchPenalty = (stability: number): number => ALPHA * (0.2 + 3.8 * Math.min(1, Math.max(0, stability)));

/** Best path through the frames: maximise evidence minus a cost for each change of chord.
 *  State `scores[t].length - 1` is "no chord". Runs in time proportional to frames x states. */
export function viterbi(scores: readonly Float32Array[], penalty: number): Int16Array {
  const T = scores.length;
  if (T === 0) return new Int16Array(0);
  const S = (scores[0] as Float32Array).length;
  const back = new Int16Array(T * S);
  let best = Float64Array.from(scores[0] as Float32Array, (v) => ALPHA * v);
  let next = new Float64Array(S);
  for (let t = 1; t < T; t++) {
    let top = 0;
    for (let s = 1; s < S; s++) if ((best[s] as number) > (best[top] as number)) top = s;
    const jump = (best[top] as number) - penalty;
    const e = scores[t] as Float32Array;
    for (let s = 0; s < S; s++) {
      const stay = best[s] as number;
      if (stay >= jump) {
        next[s] = stay + ALPHA * (e[s] as number);
        back[t * S + s] = s;
      } else {
        next[s] = jump + ALPHA * (e[s] as number);
        back[t * S + s] = top;
      }
    }
    [best, next] = [next, best];
  }
  const path = new Int16Array(T);
  let s = 0;
  for (let k = 1; k < S; k++) if ((best[k] as number) > (best[s] as number)) s = k;
  for (let t = T - 1; t >= 0; t--) {
    path[t] = s;
    s = back[t * S + s] as number;
  }
  return path;
}

export type AudioRegion = {
  start: number;
  end: number;
  label: string;
  scores: Record<string, number>;
  bass_pc: number | null;
  pitch_classes: number[] | null;
};

export type DecodeOptions = { set: ChordSet; stability: number; minDuration: number };
export const DEFAULT_DECODE: DecodeOptions = { set: "sevenths", stability: 0.5, minDuration: 0.4 };

type Run = { from: number; to: number; state: number }; // frames [from, to)

const runsOf = (path: Int16Array): Run[] => {
  const runs: Run[] = [];
  for (let t = 0; t < path.length; t++) {
    const last = runs.at(-1);
    if (last && last.state === path[t]) last.to = t + 1;
    else runs.push({ from: t, to: t + 1, state: path[t] as number });
  }
  return runs;
};

/** Absorb runs shorter than `minFrames` into the neighbour that explains them better. */
function absorbShort(runs: Run[], minFrames: number, meanScore: (r: Run, state: number) => number): Run[] {
  let out = runs.map((r) => ({ ...r }));
  for (;;) {
    const i = out.findIndex((r, k) => r.to - r.from < minFrames && out.length > 1 && k >= 0);
    if (i < 0) break;
    const r = out[i] as Run;
    const left = out[i - 1];
    const right = out[i + 1];
    const toLeft = !right || (left && meanScore(r, left.state) >= meanScore(r, right.state));
    if (toLeft && left) left.to = r.to;
    else if (right) right.from = r.from;
    out.splice(i, 1);
    const merged: Run[] = [];
    for (const x of out) {
      const last = merged.at(-1);
      if (last && last.state === x.state) last.to = x.to;
      else merged.push(x);
    }
    out = merged;
  }
  return out;
}

export function decodeChords(track: ChromaTrack, options: Partial<DecodeOptions> = {}): AudioRegion[] {
  const o = { ...DEFAULT_DECODE, ...options };
  const T = track.chroma.length;
  if (T === 0) return [];
  const templates = buildTemplates(o.set);
  const S = templates.length + 1;
  const loud = percentile(track.rms, 0.95);
  const scores: Float32Array[] = [];
  for (let t = 0; t < T; t++) {
    const row = new Float32Array(S);
    scoreFrame(track.chroma[t] as Float32Array, templates, row.subarray(0, S - 1));
    row[S - 1] = noChordScore(track.chroma[t] as Float32Array, track.rms[t] as number, loud);
    scores.push(row);
  }
  const path = viterbi(scores, switchPenalty(o.stability));
  const meanOver = (r: Run, state: number): number => {
    let s = 0;
    for (let t = r.from; t < r.to; t++) s += (scores[t] as Float32Array)[state] as number;
    return s / (r.to - r.from);
  };
  const hopSec = track.hop / track.sampleRate;
  const minFrames = Math.max(1, Math.round(o.minDuration / hopSec));
  const runs = absorbShort(runsOf(path), minFrames, meanOver);

  return runs.map((r, i): AudioRegion => {
    const start = i === 0 ? 0 : Math.max(0, frameTime(r.from, track.sampleRate, track.frame, track.hop) - hopSec / 2);
    const end = i === runs.length - 1 ? track.duration : Math.max(start, frameTime(r.to, track.sampleRate, track.frame, track.hop) - hopSec / 2);
    if (r.state === S - 1) return { start, end, label: NO_CHORD, scores: {}, bass_pc: null, pitch_classes: null };

    const n = r.to - r.from;
    const mean = new Float32Array(S - 1);
    const chroma = new Float64Array(12);
    const bassVotes = new Array<number>(12).fill(0);
    for (let t = r.from; t < r.to; t++) {
      const row = scores[t] as Float32Array;
      for (let k = 0; k < S - 1; k++) mean[k] = (mean[k] as number) + (row[k] as number) / n;
      const c = track.chroma[t] as Float32Array;
      let norm = 0;
      for (let i = 0; i < 12; i++) norm += (c[i] as number) ** 2;
      norm = Math.sqrt(norm) || 1;
      for (let i = 0; i < 12; i++) chroma[i] = (chroma[i] as number) + (c[i] as number) / norm / n;
      const b = track.bass[t] as number;
      if (b >= 0) bassVotes[b] = (bassVotes[b] as number) + 1;
    }
    const ranked = [...mean.keys()].sort((a, b) => (mean[b] as number) - (mean[a] as number));
    const chosen = r.state;
    const top = [chosen, ...ranked.filter((k) => k !== chosen)].slice(0, 6);
    const scoresOut: Record<string, number> = {};
    for (const k of top) scoresOut[(templates[k] as Template).label] = Math.round((mean[k] as number) * 1000) / 1000;

    const peak = Math.max(...chroma);
    const pcs = [...chroma.keys()].filter((i) => (chroma[i] as number) >= PITCH_EVIDENCE_RATIO * peak).sort((a, b) => (chroma[b] as number) - (chroma[a] as number)).slice(0, 6);
    const bestBass = bassVotes.indexOf(Math.max(...bassVotes));
    const bass = (bassVotes[bestBass] as number) >= 0.4 * n ? bestBass : null;
    return { start, end, label: (templates[chosen] as Template).label, scores: scoresOut, bass_pc: bass, pitch_classes: pcs };
  });
}
