/** Chroma extraction: how much energy each of the twelve pitch classes has in a short window of
 *  audio, plus the strongest low note (the bass). No chord decisions are made here.
 *
 *  Method: windowed FFT, then spectral peaks with parabolic interpolation (so a peak is placed
 *  within a fraction of a bin, which matters for low notes where semitones are only a few Hz
 *  apart). Each peak adds its compressed magnitude to its nearest pitch class, with A4 = 440 Hz.
 *
 *  Harmonics: a note also sounds at 2x, 3x, 4x... its frequency. The ones at 3x, 5x, 6x and 7x
 *  fall on other pitch classes (the third of a major chord has a 3x partial on the chord's major
 *  seventh), which would make a plain triad look like a seventh chord. A peak with a clearly
 *  stronger peak at 1/3, 1/5, 1/6 or 1/7 of its frequency is therefore counted at a fraction of
 *  its size. Octave partials (2x, 4x) are left alone, since they have the same pitch class. A low
 *  (bass) note is only a "parent" for its 3rd and 7th partials: its 5th and 6th partials are the
 *  third and fifth of its own chord and must not be discounted.
 *
 *  Limits: a note more than about 40 cents away from 440-Hz tuning is assigned to the wrong
 *  pitch class; a real chord tone that happens to sit exactly at one of those multiples of
 *  another note is under-counted; percussion and noise add energy everywhere. */

import { fft, hann } from "./fft";

export const SAMPLE_RATE = 11025;
export const FRAME = 4096;
export const HOP = 1024;
const MAIN_LO = 80;
const MAIN_HI = 2400;
const BASS_LO = 40;
const BASS_HI = 230;
const PEAK_FLOOR = 0.04; // a peak must reach this fraction of the frame's strongest peak
const COMPRESS = 0.6;
/** Partials that land on other pitch classes. A bass note's 5th and 6th partials are the third and
 *  fifth of its own chord, so a bass parent only discounts the 3rd and 7th. */
const PARTIAL_DIVISORS = [3, 5, 6, 7] as const;
const BASS_PARENT_DIVISORS: ReadonlySet<number> = new Set([3, 7]);
const PARTIAL_TOLERANCE = 0.025; // 2.5% of the frequency, about 43 cents
const PARTIAL_DOMINANCE = 2.2; // the lower peak must be this many times stronger: a harmonic is much weaker than its note, a real chord tone is not
export const PARTIAL_DISCOUNT = 0.3;

export type ChromaTrack = {
  sampleRate: number;
  frame: number;
  hop: number;
  /** Seconds of audio analysed. */
  duration: number;
  /** One 12-value vector per frame, in pitch classes C=0 ... B=11, not normalised. */
  chroma: Float32Array[];
  /** Pitch class of the strongest bass peak in each frame, or -1 when there is none. */
  bass: Int8Array;
  /** Root-mean-square level of each frame. */
  rms: Float32Array;
};

export const frameCount = (samples: number, frame = FRAME, hop = HOP): number => (samples < frame ? (samples > 0 ? 1 : 0) : 1 + Math.floor((samples - frame) / hop));

/** Time at the centre of frame `t`. */
export const frameTime = (t: number, sampleRate = SAMPLE_RATE, frame = FRAME, hop = HOP): number => (t * hop + frame / 2) / sampleRate;

const pcOf = (freq: number): number => {
  const midi = 69 + 12 * Math.log2(freq / 440);
  return ((Math.round(midi) % 12) + 12) % 12;
};

export class ChromaExtractor {
  private readonly window = hann(FRAME);
  private readonly re = new Float64Array(FRAME);
  private readonly im = new Float64Array(FRAME);
  private readonly mag = new Float64Array(FRAME / 2);

  constructor(
    private readonly samples: Float32Array,
    readonly sampleRate: number = SAMPLE_RATE,
  ) {}

  get frames(): number {
    return frameCount(this.samples.length);
  }

  /** Analyse frame `t` into `chromaOut` (12 values); returns its bass pitch class and level. */
  frame(t: number, chromaOut: Float32Array): { bass: number; rms: number } {
    const { re, im, mag, window, samples } = this;
    const start = t * HOP;
    let energy = 0;
    for (let i = 0; i < FRAME; i++) {
      const s = start + i < samples.length ? (samples[start + i] as number) : 0;
      energy += s * s;
      re[i] = s * (window[i] as number);
      im[i] = 0;
    }
    const rms = Math.sqrt(energy / FRAME);
    fft(re, im);
    let peakMax = 0;
    for (let k = 0; k < FRAME / 2; k++) {
      mag[k] = Math.hypot(re[k] as number, im[k] as number);
    }
    const binHz = this.sampleRate / FRAME;
    const peaks: { f: number; m: number }[] = [];
    for (let k = 2; k < FRAME / 2 - 2; k++) {
      const b = mag[k] as number;
      const a = mag[k - 1] as number;
      const c = mag[k + 1] as number;
      if (b > a && b >= c) {
        const denom = a - 2 * b + c;
        const delta = denom === 0 ? 0 : (0.5 * (a - c)) / denom;
        const m = b - 0.25 * (a - c) * delta;
        peaks.push({ f: (k + delta) * binHz, m });
        if (m > peakMax) peakMax = m;
      }
    }
    chromaOut.fill(0);
    let bassMag = 0;
    let bassPc = -1;
    if (peakMax > 0) {
      const floor = peakMax * PEAK_FLOOR;
      const strong = peaks.filter((q) => q.m >= floor);
      for (const p of peaks) {
        if (p.m < floor) continue;
        if (p.f >= MAIN_LO && p.f <= MAIN_HI) {
          const pc = pcOf(p.f);
          const isPartial = PARTIAL_DIVISORS.some((d) => strong.some((q) => q !== p && (q.f >= BASS_HI || BASS_PARENT_DIVISORS.has(d)) && q.m >= PARTIAL_DOMINANCE * p.m && Math.abs(q.f * d - p.f) <= PARTIAL_TOLERANCE * p.f));
          chromaOut[pc] = (chromaOut[pc] as number) + (isPartial ? PARTIAL_DISCOUNT : 1) * p.m ** COMPRESS;
        }
        if (p.f >= BASS_LO && p.f <= BASS_HI && p.m > bassMag) {
          bassMag = p.m;
          bassPc = pcOf(p.f);
        }
      }
      if (bassMag < peakMax * 0.25) bassPc = -1; // a bass peak this weak is not the bass note
    }
    return { bass: bassPc, rms };
  }
}

/** All frames at once. Fine for tests and short clips; the UI uses `extractAsync`. */
export function extractChroma(samples: Float32Array, sampleRate = SAMPLE_RATE): ChromaTrack {
  const ex = new ChromaExtractor(samples, sampleRate);
  const n = ex.frames;
  const chroma: Float32Array[] = [];
  const bass = new Int8Array(n);
  const rms = new Float32Array(n);
  for (let t = 0; t < n; t++) {
    const c = new Float32Array(12);
    const r = ex.frame(t, c);
    chroma.push(c);
    bass[t] = r.bass;
    rms[t] = r.rms;
  }
  return { sampleRate, frame: FRAME, hop: HOP, duration: samples.length / sampleRate, chroma, bass, rms };
}

/** The same, in slices that give the page time to breathe, with progress and cancellation. */
export async function extractAsync(
  samples: Float32Array,
  opts: { sampleRate?: number; signal?: AbortSignal; onProgress?: (fraction: number) => void } = {},
): Promise<ChromaTrack> {
  const sampleRate = opts.sampleRate ?? SAMPLE_RATE;
  const ex = new ChromaExtractor(samples, sampleRate);
  const n = ex.frames;
  const chroma: Float32Array[] = [];
  const bass = new Int8Array(n);
  const rms = new Float32Array(n);
  let sliceStart = performance.now();
  for (let t = 0; t < n; t++) {
    const c = new Float32Array(12);
    const r = ex.frame(t, c);
    chroma.push(c);
    bass[t] = r.bass;
    rms[t] = r.rms;
    if (performance.now() - sliceStart > 24) {
      if (opts.signal?.aborted) throw new DOMException("Analysis cancelled", "AbortError");
      opts.onProgress?.(t / n);
      await new Promise((r2) => setTimeout(r2, 0));
      sliceStart = performance.now();
    }
  }
  opts.onProgress?.(1);
  return { sampleRate, frame: FRAME, hop: HOP, duration: samples.length / sampleRate, chroma, bass, rms };
}
