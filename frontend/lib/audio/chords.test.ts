import { describe, expect, it } from "vitest";
import { type ChromaTrack, extractChroma } from "./chroma";
import {
  type AudioRegion,
  CHORD_SETS,
  NO_CHORD,
  PITCH_EVIDENCE_RATIO,
  PITCH_NAMES,
  QUALITIES,
  buildTemplates,
  decodeChords,
  noChordScore,
  peakiness,
  scoreFrame,
  switchPenalty,
  viterbi,
} from "./chords";
import { QUALITY_INTERVALS, noise, synthProgression, voicing } from "./synth";

const track = (x: Float32Array): ChromaTrack => extractChroma(x);
const labels = (r: AudioRegion[]): string[] => r.map((g) => g.label);
const chordAudio = (root: number, quality: string, seconds: number, opts: { cents?: number; bassPc?: number } = {}) => {
  const v = voicing(root, QUALITY_INTERVALS[quality] as number[]);
  return { notes: v.notes, bass: opts.bassPc !== undefined ? 36 + opts.bassPc : v.bass, seconds };
};
const name = (root: number, q: string) => `${PITCH_NAMES[root]}:${q}`;

describe("templates and scoring", () => {
  it("has twelve roots for every quality", () => {
    expect(buildTemplates("sevenths")).toHaveLength(60);
    expect(buildTemplates("triads")).toHaveLength(24);
    expect(CHORD_SETS.triads).toEqual(["maj", "min"]);
  });
  it("every template is a unit vector and labelled in Harte style", () => {
    for (const t of buildTemplates("sevenths")) {
      expect(Math.hypot(...t.vec)).toBeCloseTo(1, 6);
      expect(t.label).toMatch(/^[A-G]#?:(maj|min|7|maj7|min7)$/);
    }
  });
  it("a template scores 1 against itself", () => {
    const ts = buildTemplates("sevenths");
    const out = new Float32Array(ts.length);
    for (const t of ts) {
      scoreFrame(t.vec, ts, out);
      expect(out[ts.indexOf(t)]).toBeCloseTo(1, 5);
      expect(Math.max(...out)).toBeLessThanOrEqual(1);
    }
  });
  it("an empty frame scores zero everywhere", () => {
    const ts = buildTemplates("triads");
    const out = new Float32Array(ts.length).fill(9);
    scoreFrame(new Float32Array(12), ts, out);
    expect(Array.from(out).every((v) => v === 0)).toBe(true);
  });
  it("peakiness: flat is about 1, a triad about 4, empty is 0", () => {
    expect(peakiness(new Float32Array(12).fill(1))).toBeCloseTo(1, 6);
    expect(peakiness(Float32Array.from([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0]))).toBeCloseTo(4, 6);
    expect(peakiness(new Float32Array(12))).toBe(0);
  });
  it("no-chord score: silence high, flat high, a clear chord low", () => {
    const flat = new Float32Array(12).fill(1);
    const triad = Float32Array.from([1, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0]);
    expect(noChordScore(triad, 0, 0.3)).toBe(1);
    expect(noChordScore(flat, 0.2, 0.3)).toBeGreaterThan(0.8);
    expect(noChordScore(triad, 0.2, 0.3)).toBe(0);
  });
});

describe("viterbi", () => {
  const frames = (rows: number[][]): Float32Array[] => rows.map((r) => Float32Array.from(r));
  it("with no cost for changing it just follows the best state", () => {
    const path = viterbi(frames([[1, 0.2], [0.2, 1], [1, 0.2], [0.2, 1]]), 0);
    expect(Array.from(path)).toEqual([0, 1, 0, 1]);
  });
  it("with a high cost it does not flap on a short blip", () => {
    const rows = [...Array(6).fill([1, 0.3]), [0.3, 1], ...Array(6).fill([1, 0.3])];
    expect(new Set(viterbi(frames(rows), switchPenalty(0.5))).size).toBe(1);
  });
  it("still follows a change that lasts", () => {
    const rows = [...Array(10).fill([1, 0.2]), ...Array(10).fill([0.2, 1])];
    const path = Array.from(viterbi(frames(rows), switchPenalty(0.5)));
    expect(path.slice(0, 10).every((s) => s === 0)).toBe(true);
    expect(path.slice(10).every((s) => s === 1)).toBe(true);
  });
  it("handles no frames and one frame", () => {
    expect(viterbi([], 5)).toHaveLength(0);
    expect(Array.from(viterbi(frames([[0.1, 0.9]]), 5))).toEqual([1]);
  });
  it("the cost grows with stability", () => {
    expect(switchPenalty(0)).toBeLessThan(switchPenalty(0.5));
    expect(switchPenalty(0.5)).toBeLessThan(switchPenalty(1));
    expect(switchPenalty(-3)).toBe(switchPenalty(0));
    expect(switchPenalty(9)).toBe(switchPenalty(1));
  });
});

describe("single chords (synthesised, clean)", () => {
  it("all 60 chords are identified exactly", () => {
    const wrong: string[] = [];
    for (let root = 0; root < 12; root++) {
      for (const q of QUALITIES) {
        const r = decodeChords(track(synthProgression([chordAudio(root, q, 2)])));
        if (r.length !== 1 || r[0]?.label !== name(root, q)) wrong.push(`${name(root, q)} -> ${labels(r).join(",")}`);
      }
    }
    expect(wrong).toEqual([]);
  });
  it("triads-only mode names a major and minor chord and does not invent sevenths", () => {
    for (let root = 0; root < 12; root++) {
      for (const q of ["maj", "min"] as const) {
        const r = decodeChords(track(synthProgression([chordAudio(root, q, 2)])), { set: "triads" });
        expect(labels(r)).toEqual([name(root, q)]);
      }
    }
    const seventh = decodeChords(track(synthProgression([chordAudio(0, "7", 2)])), { set: "triads" });
    expect(labels(seventh).every((l) => /:(maj|min)$/.test(l) || l === NO_CHORD)).toBe(true);
  });
  it("reports the bass note, including when it is not the root", () => {
    const rootPos = decodeChords(track(synthProgression([chordAudio(0, "maj", 2)])))[0];
    expect(rootPos?.bass_pc).toBe(0);
    // C over E. The bass note's own third harmonic is B, the major seventh of C, so plain C and
    // Cmaj7 are nearly tied here. The bass is still reported correctly, and the right chord stays
    // a close runner-up, which is what lets the server flag the region as ambiguous.
    const inversion = decodeChords(track(synthProgression([chordAudio(0, "maj", 2, { bassPc: 4 })])))[0] as AudioRegion;
    expect(inversion.bass_pc).toBe(4);
    const top = Math.max(...Object.values(inversion.scores));
    expect(top - (inversion.scores["C:maj"] ?? 0)).toBeLessThan(0.1);
    const second = decodeChords(track(synthProgression([chordAudio(0, "maj", 2, { bassPc: 7 })])))[0];
    expect(second?.bass_pc).toBe(7);
  });
  it("reports the pitch classes that carry the chord", () => {
    const r = decodeChords(track(synthProgression([chordAudio(0, "maj7", 2)])))[0] as AudioRegion;
    expect(r.pitch_classes).toEqual(expect.arrayContaining([0, 4, 7, 11]));
  });
  it("on clean audio the reported pitch evidence is exactly the chord's own tones, for all 60 chords", () => {
    const wrong: string[] = [];
    for (let root = 0; root < 12; root++) {
      for (const q of QUALITIES) {
        const r = decodeChords(track(synthProgression([chordAudio(root, q, 2)])))[0] as AudioRegion;
        const want = [...new Set((QUALITY_INTERVALS[q] as number[]).map((i) => (root + i) % 12))].sort((a, b) => a - b);
        const got = [...(r.pitch_classes ?? [])].sort((a, b) => a - b);
        if (got.join() !== want.join()) wrong.push(`${name(root, q)}: ${got.join(",")} (wanted ${want.join(",")})`);
      }
    }
    expect(wrong).toEqual([]);
    expect(PITCH_EVIDENCE_RATIO).toBeGreaterThan(0.13); // above the strongest non-chord pitch class measured
    expect(PITCH_EVIDENCE_RATIO).toBeLessThan(0.35); // below the weakest genuine chord tone measured
  });
  it("a bare melody note is ambiguous: its best readings are almost tied", () => {
    const x = synthProgression([{ notes: [60], seconds: 2 }]);
    const r = decodeChords(track(x), { set: "triads" })[0] as AudioRegion;
    const sorted = Object.values(r.scores).sort((a, b) => b - a);
    expect(sorted[0]! - sorted[1]!).toBeLessThan(0.1); // the server will flag this as ambiguous
  });
  it("a major triad and a major seventh are told apart, but a triad is not mistaken for a seventh", () => {
    const tri = decodeChords(track(synthProgression([chordAudio(2, "maj", 2)])))[0] as AudioRegion;
    const sev = decodeChords(track(synthProgression([chordAudio(2, "maj7", 2)])))[0] as AudioRegion;
    expect([tri.label, sev.label]).toEqual(["D:maj", "D:maj7"]);
    expect(sev.scores["D:maj7"]! - (sev.scores["D:maj"] ?? 0)).toBeGreaterThan(0.05);
  });
});

describe("progressions", () => {
  const chordsIn = (key: number, spec: [number, string][], seconds: number) => spec.map(([semis, q]) => chordAudio((key + semis) % 12, q, seconds));
  it("ii-V-I-vi in all twelve keys: right chords, in order, change times within a third of a second", () => {
    const wrong: string[] = [];
    for (let key = 0; key < 12; key++) {
      const spec: [number, string][] = [[2, "min7"], [7, "7"], [0, "maj7"], [9, "min7"]];
      const x = synthProgression(chordsIn(key, spec, 2));
      const r = decodeChords(track(x));
      const want = spec.map(([s, q]) => name((key + s) % 12, q));
      if (labels(r).join() !== want.join()) {
        wrong.push(`key ${key}: ${labels(r).join(",")} (wanted ${want.join(",")})`);
        continue;
      }
      r.slice(1).forEach((g, i) => {
        if (Math.abs(g.start - 2 * (i + 1)) > 0.33) wrong.push(`key ${key}: change ${i + 1} at ${g.start.toFixed(2)}s`);
      });
    }
    expect(wrong).toEqual([]);
  });
  it("I-V-vi-IV with triads in all twelve keys", () => {
    const wrong: string[] = [];
    for (let key = 0; key < 12; key++) {
      const spec: [number, string][] = [[0, "maj"], [7, "maj"], [9, "min"], [5, "maj"]];
      const r = decodeChords(track(synthProgression(chordsIn(key, spec, 1.5))), { set: "triads" });
      const want = spec.map(([s, q]) => name((key + s) % 12, q));
      if (labels(r).join() !== want.join()) wrong.push(`key ${key}: ${labels(r).join(",")}`);
    }
    expect(wrong).toEqual([]);
  });
  it("the same chord repeated is one region, not several", () => {
    const x = synthProgression([chordAudio(7, "maj", 1.5), chordAudio(7, "maj", 1.5)]);
    expect(labels(decodeChords(track(x)))).toEqual(["G:maj"]);
  });
  it("copes with a recording tuned 25 cents sharp", () => {
    const x = synthProgression([chordAudio(0, "maj", 2), chordAudio(9, "min", 2), chordAudio(5, "maj", 2), chordAudio(7, "7", 2)], { cents: 25 });
    expect(labels(decodeChords(track(x)))).toEqual(["C:maj", "A:min", "F:maj", "G:7"]);
  });
  it("regions are contiguous: start at 0, end at the length, no gaps or overlaps", () => {
    const x = synthProgression([chordAudio(0, "maj", 2), chordAudio(9, "min", 2), chordAudio(5, "maj", 2)]);
    const t = track(x);
    const r = decodeChords(t);
    expect(r[0]?.start).toBe(0);
    expect(r.at(-1)?.end).toBeCloseTo(t.duration, 9);
    for (let i = 1; i < r.length; i++) expect(r[i]?.start).toBeCloseTo(r[i - 1]?.end as number, 9);
    expect(r.every((g) => g.end > g.start)).toBe(true);
  });
  it("each region's reported scores include the label it chose, within 0 and 1", () => {
    const x = synthProgression([chordAudio(0, "maj", 2), chordAudio(2, "min7", 2)]);
    for (const g of decodeChords(track(x))) {
      expect(Object.keys(g.scores)).toContain(g.label);
      expect(Object.values(g.scores).every((v) => v >= 0 && v <= 1)).toBe(true);
      expect(Object.keys(g.scores).length).toBeLessThanOrEqual(6);
    }
  });
  it("is deterministic", () => {
    const x = synthProgression([chordAudio(0, "maj", 2), chordAudio(9, "min", 2)]);
    expect(decodeChords(track(x))).toEqual(decodeChords(track(x)));
  });
});

describe("silence and noise: no chord is invented", () => {
  it("silence is one no-chord region", () => {
    expect(decodeChords(track(new Float32Array(11025 * 3)))).toEqual([{ start: 0, end: 3, label: NO_CHORD, scores: {}, bass_pc: null, pitch_classes: null }]);
  });
  it("noise alone is no chord", () => {
    const r = decodeChords(track(noise(11025 * 4, 0.2)));
    expect(labels(r)).toEqual([NO_CHORD]);
  });
  it("a chord between two silences is found, with no-chord on either side", () => {
    const x = synthProgression([{ notes: [], seconds: 1.5 }, chordAudio(0, "maj", 2), { notes: [], seconds: 1.5 }]);
    const r = decodeChords(track(x));
    expect(labels(r)).toEqual([NO_CHORD, "C:maj", NO_CHORD]);
    expect(r[1]?.start).toBeGreaterThan(1.2);
    expect(r[1]?.start).toBeLessThan(1.8);
  });
  it("a chord under moderate noise is still right", () => {
    const x = synthProgression([chordAudio(0, "maj", 3)]);
    const n = noise(x.length, 0.05, 7);
    x.forEach((v, i) => {
      x[i] = v + (n[i] as number);
    });
    expect(labels(decodeChords(track(x)))).toEqual(["C:maj"]);
  });
  it("heavier noise lowers the evidence it reports, rather than keeping the same confidence", () => {
    const clean = synthProgression([chordAudio(0, "maj", 3)]);
    const messy = Float32Array.from(clean);
    const n = noise(clean.length, 0.35, 11);
    messy.forEach((v, i) => {
      messy[i] = v + (n[i] as number);
    });
    const a = decodeChords(track(clean))[0] as AudioRegion;
    const b = decodeChords(track(messy)).find((g) => g.label !== NO_CHORD);
    if (b) expect(b.scores[b.label] as number).toBeLessThan(a.scores["C:maj"] as number);
  });
});

describe("stability and short changes", () => {
  it("a very short passing chord is absorbed when the minimum length is long enough", () => {
    const x = synthProgression([chordAudio(0, "maj", 2), chordAudio(7, "maj", 0.25), chordAudio(0, "maj", 2)]);
    expect(labels(decodeChords(track(x), { minDuration: 0.6, stability: 0.8 }))).toEqual(["C:maj"]);
  });
  it("more stability never gives more regions", () => {
    const x = synthProgression([chordAudio(0, "maj", 1.2), chordAudio(2, "min", 0.5), chordAudio(0, "maj", 1.2), chordAudio(7, "maj", 0.5), chordAudio(0, "maj", 1.2)]);
    const t = track(x);
    const counts = [0, 0.25, 0.5, 0.75, 1].map((s) => decodeChords(t, { stability: s, minDuration: 0.1 }).length);
    for (let i = 1; i < counts.length; i++) expect(counts[i]).toBeLessThanOrEqual(counts[i - 1] as number);
    expect(counts[0]).toBeGreaterThan(counts.at(-1) as number);
  });
  it("nothing to decode gives no regions", () => {
    expect(decodeChords({ ...track(new Float32Array(10)), chroma: [], bass: new Int8Array(0), rms: new Float32Array(0) })).toEqual([]);
  });
});
