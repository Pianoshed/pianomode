import { describe, expect, it } from "vitest";
import { ChromaExtractor, FRAME, HOP, PARTIAL_DISCOUNT, SAMPLE_RATE, extractAsync, extractChroma, frameCount, frameTime } from "./chroma";
import { fft, hann, isPowerOfTwo } from "./fft";
import { addNotes, hz, noise, synthProgression } from "./synth";

const argmax = (v: ArrayLike<number>): number => {
  let best = 0;
  for (let i = 1; i < v.length; i++) if ((v[i] as number) > (v[best] as number)) best = i;
  return best;
};
const mean = (frames: Float32Array[]): Float32Array => {
  const out = new Float32Array(12);
  for (const f of frames) for (let i = 0; i < 12; i++) out[i] = (out[i] as number) + (f[i] as number) / frames.length;
  return out;
};
const sine = (f: number, seconds: number): Float32Array => {
  const out = new Float32Array(Math.round(seconds * SAMPLE_RATE));
  for (let i = 0; i < out.length; i++) out[i] = 0.3 * Math.sin((2 * Math.PI * f * i) / SAMPLE_RATE);
  return out;
};

describe("fft", () => {
  it("puts a sine at the right bin", () => {
    const n = 1024;
    const re = new Float64Array(n);
    const im = new Float64Array(n);
    for (let i = 0; i < n; i++) re[i] = Math.sin((2 * Math.PI * 50 * i) / n);
    fft(re, im);
    const mags = Array.from(re, (r, i) => Math.hypot(r, im[i]!)).slice(0, n / 2);
    expect(argmax(mags)).toBe(50);
    expect(mags[50]).toBeCloseTo(n / 2, 3);
  });
  it("turns an impulse into a flat spectrum", () => {
    const re = new Float64Array(8);
    const im = new Float64Array(8);
    re[0] = 1;
    fft(re, im);
    expect(Array.from(re)).toEqual(new Array(8).fill(1));
    expect(Array.from(im).every((x) => Math.abs(x) < 1e-12)).toBe(true);
  });
  it("conserves energy (Parseval)", () => {
    const n = 256;
    const re = Float64Array.from({ length: n }, (_, i) => Math.sin(i * 0.37) + 0.3 * Math.cos(i * 1.9));
    const im = new Float64Array(n);
    const time = re.reduce((s, x) => s + x * x, 0);
    fft(re, im);
    const freq = re.reduce((s, x, i) => s + x * x + im[i]! * im[i]!, 0) / n;
    expect(freq).toBeCloseTo(time, 6);
  });
  it("refuses lengths that are not a power of two or arrays that differ", () => {
    expect(() => fft(new Float64Array(6), new Float64Array(6))).toThrow(RangeError);
    expect(() => fft(new Float64Array(8), new Float64Array(4))).toThrow(RangeError);
    expect(isPowerOfTwo(4096)).toBe(true);
    expect(isPowerOfTwo(0)).toBe(false);
    expect(isPowerOfTwo(12)).toBe(false);
  });
  it("hann window is zero at the start and peaks in the middle", () => {
    const w = hann(8);
    expect(w[0]).toBe(0);
    expect(w[4]).toBeCloseTo(1, 12);
  });
});

describe("frame bookkeeping", () => {
  it("counts frames", () => {
    expect(frameCount(0)).toBe(0);
    expect(frameCount(100)).toBe(1);
    expect(frameCount(FRAME)).toBe(1);
    expect(frameCount(FRAME + HOP)).toBe(2);
    expect(frameCount(FRAME + 3 * HOP - 1)).toBe(3);
  });
  it("frame times are at the frame centre", () => {
    expect(frameTime(0)).toBeCloseTo(FRAME / 2 / SAMPLE_RATE, 9);
    expect(frameTime(10) - frameTime(9)).toBeCloseTo(HOP / SAMPLE_RATE, 9);
  });
});

describe("chroma", () => {
  it("a 440 Hz tone is pitch class A", () => {
    const c = mean(extractChroma(sine(440, 1)).chroma);
    expect(argmax(c)).toBe(9);
    expect(c[9]).toBeGreaterThan(5 * (c.reduce((a, b) => a + b, 0) - (c[9] as number)) / 11);
  });
  it.each([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])("a pure tone on pitch class %i is found", (pc) => {
    const c = mean(extractChroma(sine(hz(60 + pc), 1)).chroma);
    expect(argmax(c)).toBe(pc);
  });
  it("a C major chord lights up C, E and G", () => {
    const x = new Float32Array(2 * SAMPLE_RATE);
    addNotes(x, 0, x.length, [60, 64, 67]);
    const c = mean(extractChroma(x).chroma);
    const top3 = [...c.keys()].sort((a, b) => (c[b] as number) - (c[a] as number)).slice(0, 3).sort((a, b) => a - b);
    expect(top3).toEqual([0, 4, 7]);
  });
  it("tolerates a recording tuned 30 cents sharp", () => {
    const x = new Float32Array(2 * SAMPLE_RATE);
    addNotes(x, 0, x.length, [60, 64, 67], { cents: 30 });
    const c = mean(extractChroma(x).chroma);
    const top3 = [...c.keys()].sort((a, b) => (c[b] as number) - (c[a] as number)).slice(0, 3).sort((a, b) => a - b);
    expect(top3).toEqual([0, 4, 7]);
  });
  it("silence gives no energy and no bass", () => {
    const t = extractChroma(new Float32Array(SAMPLE_RATE));
    expect(t.chroma.every((f) => f.every((v) => v === 0))).toBe(true);
    expect(Array.from(t.bass).every((b) => b === -1)).toBe(true);
    expect(Math.max(...t.rms)).toBe(0);
  });
  it("is deterministic", () => {
    const x = synthProgression([{ notes: [60, 64, 67], seconds: 1, bass: 36 }]);
    const a = extractChroma(x);
    const b = extractChroma(x);
    expect(a.chroma.map((f) => Array.from(f))).toEqual(b.chroma.map((f) => Array.from(f)));
  });
  it("reports the length of the audio", () => {
    expect(extractChroma(new Float32Array(SAMPLE_RATE * 3)).duration).toBeCloseTo(3, 9);
  });
});

describe("harmonics", () => {
  const chromaOf = (notes: number[], bass: number): Float32Array => mean(extractChroma(synthProgression([{ notes, bass, seconds: 2 }])).chroma);
  it("the third's own harmonic does not make a plain C triad look like it contains B", () => {
    const c = chromaOf([60, 64, 67], 36);
    expect(c[11]! / c[0]!).toBeLessThan(0.35); // B against C
    expect(c[11]!).toBeLessThan(c[4]! * 0.35); // and against E
  });
  it("a real flat seventh is still heard (it must not be mistaken for a harmonic of the bass)", () => {
    const c = chromaOf([60, 64, 67, 70], 36); // C7: C E G Bb over a C bass
    expect(c[10]!).toBeGreaterThan(0.4 * Math.max(...c));
  });
  it("a real major seventh is still heard", () => {
    const c = chromaOf([60, 64, 67, 71], 36);
    expect(c[11]!).toBeGreaterThan(0.4 * Math.max(...c));
  });
  it("the bass note's own third and fifth are not discounted", () => {
    const c = chromaOf([60, 64, 67], 36);
    expect(c[4]!).toBeGreaterThan(0.5 * Math.max(...c));
    expect(c[7]!).toBeGreaterThan(0.5 * Math.max(...c));
  });
  it("a loud bass does not erase the chord's third, which is the bass's own 5th harmonic", () => {
    const x = new Float32Array(2 * SAMPLE_RATE);
    addNotes(x, 0, x.length, [60, 64, 67], { amp: 0.05 }); // a quiet chord...
    addNotes(x, 0, x.length, [36], { amp: 0.5, partials: 8 }); // ...over a bass about ten times louder, with a rich harmonic series
    const c = mean(extractChroma(x).chroma);
    // Measured: the third keeps about 36% of the strongest pitch class with this rule, and about
    // 11% if a bass note's 5th harmonic were discounted like any other. 20% separates the two.
    expect(c[4]!).toBeGreaterThan(0.2 * Math.max(...c));
  });
  it("the discount is a fraction, not a deletion", () => {
    expect(PARTIAL_DISCOUNT).toBeGreaterThan(0);
    expect(PARTIAL_DISCOUNT).toBeLessThan(1);
  });
});

describe("bass", () => {
  const bassOf = (bassMidi: number, chord: number[]): number => {
    const x = synthProgression([{ notes: chord, seconds: 1.5, bass: bassMidi }]);
    const t = extractChroma(x);
    const votes = new Map<number, number>();
    for (const b of t.bass) votes.set(b, (votes.get(b) ?? 0) + 1);
    return [...votes.entries()].sort((a, b) => b[1] - a[1])[0]![0];
  };
  it("finds the bass note under a chord", () => {
    expect(bassOf(36, [60, 64, 67])).toBe(0); // C2 under C major
    expect(bassOf(40, [60, 64, 67])).toBe(4); // E2: a first inversion
    expect(bassOf(43, [60, 64, 67])).toBe(7); // G2
  });
  it("tells neighbouring low notes apart", () => {
    const pcs = [33, 34, 35, 36, 37, 38].map((m) => bassOf(m, [64, 67]));
    expect(pcs).toEqual([9, 10, 11, 0, 1, 2]);
  });
  it("finds nothing when there is no low note", () => {
    const x = synthProgression([{ notes: [72, 76, 79], seconds: 1.5 }]);
    expect(Array.from(extractChroma(x).bass).every((b) => b === -1)).toBe(true);
  });
});

describe("noise", () => {
  it("noise spreads evenly over the pitch classes", () => {
    const c = mean(extractChroma(noise(SAMPLE_RATE * 2, 0.2)).chroma);
    const max = Math.max(...c);
    const avg = c.reduce((a, b) => a + b, 0) / 12;
    expect(max / avg).toBeLessThan(1.6);
  });
});

describe("extractAsync", () => {
  it("gives the same result as the synchronous version and reports progress", async () => {
    const x = synthProgression([{ notes: [60, 64, 67], seconds: 2, bass: 36 }]);
    const progress: number[] = [];
    const a = await extractAsync(x, { onProgress: (p) => progress.push(p) });
    const b = extractChroma(x);
    expect(a.chroma.length).toBe(b.chroma.length);
    expect(Array.from(a.chroma[5]!)).toEqual(Array.from(b.chroma[5]!));
    expect(progress.at(-1)).toBe(1);
  });
  it("can be cancelled", async () => {
    const x = new Float32Array(SAMPLE_RATE * 120);
    const ctl = new AbortController();
    setTimeout(() => ctl.abort(), 5);
    await expect(extractAsync(x, { signal: ctl.signal })).rejects.toMatchObject({ name: "AbortError" });
  });
  it("the extractor's frame count matches", () => {
    expect(new ChromaExtractor(new Float32Array(FRAME + 5 * HOP)).frames).toBe(6);
  });
});
