import { describe, expect, it } from "vitest";
import corrected from "./__fixtures__/audio-interpret-corrected.json";
import plain from "./__fixtures__/audio-interpret.json";
import type { Correction, Hypothesis, InterpretResponse } from "./api";
import { AudioLoadError, MAX_AUDIO_BYTES, MAX_SECONDS, checkLimits } from "./decode";
import {
  AMBIGUITY_LEVELS,
  EditError,
  MIN_REGION,
  addEdit,
  buildInterpretRequest,
  cleanLabel,
  correctionSummary,
  deleteEdit,
  edgeEdits,
  gapAround,
  hypothesisAt,
  look,
  mergeEdits,
  relabelEdit,
  splitEdits,
  waveformPeaks,
} from "./studio";
import { encodeWav } from "./wav";

// Contract check: if the API response drifts from the hand-written types, `npm run typecheck` fails.
const res: InterpretResponse = plain as unknown as InterpretResponse;
const fixed: InterpretResponse = corrected as unknown as InterpretResponse;
const hyps = res.hypotheses;

describe("contract with the API (the server's real responses)", () => {
  it("flags the close call as ambiguous, keeps no-chord, and invents no confidence", () => {
    expect(hyps.map((h) => h.status)).toEqual(["ambiguous", "estimated", "no_chord", "estimated"]);
    expect(hyps.every((h) => h.confidence === null && h.calibration === null)).toBe(true);
    expect(hyps[0]!.alternatives.map((a) => a.symbol)).toEqual(["Cmaj7", "Am7"]);
  });
  it("marks a corrected region as set by the user and keeps the original estimate", () => {
    expect(fixed.hypotheses[1]).toMatchObject({ origin: "user", status: "user_set", symbol: "Am7" });
    expect(fixed.original![1]).toMatchObject({ origin: "audio", symbol: "Am" });
    expect(fixed.corrections[0]).toMatchObject({ kind: "relabel", index: 1 });
  });
  it("says estimates are not probabilities", () => {
    expect(res.evidence_note).toMatch(/not probabilities/);
  });
});

describe("ambiguity levels", () => {
  it("are ordered, and the default is the middle one", () => {
    expect(AMBIGUITY_LEVELS.fewer).toBeLessThan(AMBIGUITY_LEVELS.normal);
    expect(AMBIGUITY_LEVELS.normal).toBeLessThan(AMBIGUITY_LEVELS.more);
    expect(buildInterpretRequest([]).score_margin).toBe(AMBIGUITY_LEVELS.normal);
    expect(buildInterpretRequest([], { scoreMargin: AMBIGUITY_LEVELS.more }).score_margin).toBe(0.06);
  });
});

describe("look", () => {
  it("shows uncertainty rather than hiding it", () => {
    expect(look(hyps[0]!)).toMatchObject({ label: "C?", kind: "ambiguous" });
    expect(look(hyps[1]!)).toMatchObject({ label: "Am", kind: "estimated", sublabel: "iii" });
    expect(look(hyps[2]!)).toEqual({ label: "no chord", sublabel: null, kind: "none" });
    expect(look({ ...hyps[0]!, status: "unrecognised_label" })).toMatchObject({ label: "?", kind: "unknown" });
    expect(look(fixed.hypotheses[1]!)).toMatchObject({ label: "Am7", kind: "user" });
  });
  it("finds the region at a time (the end of one is the start of the next)", () => {
    expect([0, 1.99, 2, 5.9, 7.99, 8, -1].map((t) => hypothesisAt(hyps, t))).toEqual([0, 0, 1, 2, 3, -1, -1]);
  });
});

describe("buildInterpretRequest", () => {
  const regions = [{ start: 0, end: 1, label: "C:maj", scores: { "C:maj": 0.9 }, bass_pc: 0, pitch_classes: [0, 4, 7] }];
  it("sends regions, options and corrections through", () => {
    const c: Correction[] = [{ op: "delete", index: 0 }];
    const r = buildInterpretRequest(regions, { key: { tonic: "C", mode: "major" }, prefer: "flats", corrections: c });
    expect(r).toMatchObject({ key: { tonic: "C", mode: "major" }, prefer: "flats", min_duration: 0.25, score_margin: 0.03, corrections: c });
    expect(r.regions[0]).toEqual(regions[0]);
  });
  it("never sends a probability or a calibration", () => {
    const body = JSON.stringify(buildInterpretRequest(regions));
    expect(body).not.toMatch(/probability|calibration/);
  });
});

describe("edgeEdits: moving a boundary leaves no gap or overlap, in an order the server accepts", () => {
  // regions: [0,2) [2,4) [4,6) [6,8)
  const dur = 8;
  it("moving a shared start later shortens the earlier chord's end last", () => {
    const e = edgeEdits(hyps, 1, "start", 2.5, dur);
    expect(e).toEqual([{ op: "retime", index: 1, start: 2.5, end: 4 }, { op: "retime", index: 0, start: 0, end: 2.5 }]);
  });
  it("moving a shared start earlier shortens the region that gives up time first", () => {
    const e = edgeEdits(hyps, 1, "start", 1.5, dur);
    expect(e).toEqual([{ op: "retime", index: 0, start: 0, end: 1.5 }, { op: "retime", index: 1, start: 1.5, end: 4 }]);
  });
  it("moving a shared end later, and earlier", () => {
    expect(edgeEdits(hyps, 1, "end", 4.5, dur)).toEqual([{ op: "retime", index: 2, start: 4.5, end: 6 }, { op: "retime", index: 1, start: 2, end: 4.5 }]);
    expect(edgeEdits(hyps, 1, "end", 3.5, dur)).toEqual([{ op: "retime", index: 1, start: 2, end: 3.5 }, { op: "retime", index: 2, start: 3.5, end: 6 }]);
  });
  it("the outer edges of the first and last chord move alone", () => {
    expect(edgeEdits(hyps, 0, "start", 0.5, dur)).toEqual([{ op: "retime", index: 0, start: 0.5, end: 2 }]);
    expect(edgeEdits(hyps, 3, "end", 7, dur)).toEqual([{ op: "retime", index: 3, start: 6, end: 7 }]);
  });
  it("applying the edits in order never overlaps (checked the way the server checks)", () => {
    for (const [i, edge, to] of [[1, "start", 2.5], [1, "start", 1.5], [2, "end", 6.4], [2, "end", 5.2]] as const) {
      let cur: Hypothesis[] = hyps.map((h) => ({ ...h }));
      for (const e of edgeEdits(cur, i, edge, to, dur)) {
        if (e.op !== "retime") throw new Error("expected retime");
        cur = cur.map((h, k) => (k === e.index ? { ...h, start: e.start, end: e.end } : h));
        for (let k = 1; k < cur.length; k++) expect(cur[k]!.start).toBeGreaterThanOrEqual(cur[k - 1]!.end - 1e-6);
      }
      for (let k = 1; k < cur.length; k++) expect(cur[k]!.start).toBeCloseTo(cur[k - 1]!.end, 6); // and no gap was left
    }
  });
  it.each<[string, number, "start" | "end", number]>([
    ["past the end of the recording", 1, "end", 9],
    ["before the start", 0, "start", -1],
    ["a chord of no length", 1, "start", 4],
    ["squeezing the chord before it away", 1, "start", 0],
    ["not a number", 1, "end", Number.NaN],
    ["squeezing the next chord away", 1, "end", 6],
  ])("refuses %s", (_name, index, edge, to) => {
    expect(() => edgeEdits(hyps, index, edge, to, 8)).toThrow(EditError);
  });
  it("a region with a gap before it moves alone, and cannot grow into its neighbour", () => {
    const gappy = [hyps[0]!, { ...hyps[1]!, start: 2.5 }];
    expect(edgeEdits(gappy, 1, "start", 2.2, 8)).toEqual([{ op: "retime", index: 1, start: 2.2, end: 4 }]);
    expect(() => edgeEdits(gappy, 1, "start", 1.5, 8)).toThrow(/overlap/);
  });
});

describe("split, merge, delete, relabel, add", () => {
  it("splits a chord in two at a time, both halves keeping the label", () => {
    expect(splitEdits(hyps, 1, 3)).toEqual([{ op: "retime", index: 1, start: 2, end: 3 }, { op: "add", start: 3, end: 4, label: "A:min" }]);
  });
  it("refuses to split too close to an end or outside the chord", () => {
    expect(() => splitEdits(hyps, 1, 2.01)).toThrow(EditError);
    expect(() => splitEdits(hyps, 1, 3.99)).toThrow(EditError);
    expect(() => splitEdits(hyps, 1, 5)).toThrow(EditError);
    expect(() => splitEdits(hyps, 9, 1)).toThrow(EditError);
  });
  it("merges with the next chord: remove it first, then extend", () => {
    expect(mergeEdits(hyps, 1)).toEqual([{ op: "delete", index: 2 }, { op: "retime", index: 1, start: 2, end: 6 }]);
    expect(() => mergeEdits(hyps, 3)).toThrow(/no chord after/);
    expect(() => mergeEdits([hyps[0]!, { ...hyps[1]!, start: 2.5 }], 0)).toThrow(/gap/);
  });
  it("relabel and delete", () => {
    expect(relabelEdit(2, "  Dm7/C ")).toEqual({ op: "relabel", index: 2, label: "Dm7/C" });
    expect(deleteEdit(1)).toEqual({ op: "delete", index: 1 });
  });
  it("labels must be non-empty and not too long", () => {
    expect(() => cleanLabel("   ")).toThrow(EditError);
    expect(() => cleanLabel("C".repeat(41))).toThrow(/at most 40/);
    expect(cleanLabel("C".repeat(40))).toHaveLength(40);
  });
  it("adds a chord only in an empty stretch", () => {
    const withGap = [hyps[0]!, hyps[2]!]; // 2 s to 4 s is empty
    expect(gapAround(withGap, 3, 8)).toEqual({ start: 2, end: 4 });
    expect(gapAround(withGap, 1, 8)).toBeNull();
    expect(gapAround([hyps[0]!], 5, 8)).toEqual({ start: 2, end: 8 });
    expect(gapAround([hyps[1]!], 1, 8)).toEqual({ start: 0, end: 2 });
    expect(addEdit({ start: 2, end: 4 }, "Em")).toEqual({ op: "add", start: 2, end: 4, label: "Em" });
    expect(() => addEdit(null, "Em")).toThrow(/empty stretch/);
    expect(gapAround([{ ...hyps[0]!, end: 2 }, { ...hyps[1]!, start: 2 + MIN_REGION / 2 }], 2.01, 8)).toBeNull(); // too small to use
  });
  it("describes how many corrections there are", () => {
    expect([0, 1, 4].map(correctionSummary)).toEqual(["No corrections", "1 correction", "4 corrections"]);
  });
});

describe("waveformPeaks", () => {
  it("takes the loudest sample in each slice", () => {
    const x = Float32Array.from([0.1, -0.5, 0.2, 0.9, -0.3, 0.05]);
    const peaks = Array.from(waveformPeaks(x, 3));
    [0.5, 0.9, 0.3].forEach((want, i) => expect(peaks[i]).toBeCloseTo(want, 6)); // 32-bit floats are not exact
  });
  it("copes with empty input, zero buckets and more buckets than samples", () => {
    expect(waveformPeaks(new Float32Array(0), 10)).toHaveLength(10);
    expect(waveformPeaks(Float32Array.from([1]), 0)).toHaveLength(0);
    expect(Array.from(waveformPeaks(Float32Array.from([0.5, 0.25]), 4)).every((v) => v > 0)).toBe(true);
  });
});

describe("encodeWav", () => {
  const wav = encodeWav(Float32Array.from([0, 0.5, -0.5, 1, -1, 2]), 11025);
  const v = new DataView(wav.buffer);
  const tag = (at: number) => String.fromCharCode(...wav.subarray(at, at + 4));
  it("writes a valid 16-bit mono PCM header", () => {
    expect([tag(0), tag(8), tag(12), tag(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect(v.getUint16(20, true)).toBe(1);
    expect(v.getUint16(22, true)).toBe(1);
    expect(v.getUint32(24, true)).toBe(11025);
    expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(12);
    expect(v.getUint32(4, true)).toBe(wav.length - 8);
    expect(wav.length).toBe(44 + 12);
  });
  it("converts samples and clips anything outside -1 to 1", () => {
    expect([0, 1, 2, 3, 4, 5].map((i) => v.getInt16(44 + i * 2, true))).toEqual([0, 16384, -16383, 32767, -32767, 32767]); // -16383.5 rounds up; the half-sample is inaudible
  });
});

describe("file limits", () => {
  it("refuses a file that is too big, too long or too short, each with a reason", () => {
    expect(() => checkLimits(MAX_AUDIO_BYTES + 1)).toThrowError(expect.objectContaining({ code: "too_large" }));
    expect(() => checkLimits(1000, MAX_SECONDS + 1)).toThrowError(expect.objectContaining({ code: "too_long" }));
    expect(() => checkLimits(1000, 0.1)).toThrowError(expect.objectContaining({ code: "too_short" }));
    expect(() => checkLimits(MAX_AUDIO_BYTES, MAX_SECONDS)).not.toThrow();
    expect(() => checkLimits(1000)).not.toThrow();
    try {
      checkLimits(1000, MAX_SECONDS + 1);
    } catch (e) {
      expect(e).toBeInstanceOf(AudioLoadError);
      expect((e as Error).message).toMatch(/10 minutes/);
    }
  });
});
