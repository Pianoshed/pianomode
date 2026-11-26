import { describe, expect, it } from "vitest";
import {
  intervalLabel,
  nameToPc,
  overlayFromCandidate,
  overlayFromChord,
  overlayFromScale,
  overlayFromVoicing,
} from "./highlight";
import type { ChordConstruct, ChordIdentify, ScaleResult, VoicingsResult } from "./theoryApi";
import cOverD from "./__fixtures__/chord-c-over-d.json";
import cmaj7 from "./__fixtures__/chord-cmaj7.json";
import dm7OverC from "./__fixtures__/chord-dm7-over-c.json";
import gbMajor from "./__fixtures__/chord-gb-major.json";
import identifyAm7 from "./__fixtures__/identify-am7.json";
import identifyFirst from "./__fixtures__/identify-first-inversion.json";
import fsharp from "./__fixtures__/scale-f-sharp-major.json";
import voicings from "./__fixtures__/voicings-cmaj7.json";

describe("note names", () => {
  it("reads spelled names to pitch classes, including theoretical spellings", () => {
    const cases: [string, number][] = [["C", 0], ["Eb", 3], ["F#", 6], ["B#", 0], ["Cb", 11], ["E#", 5], ["Bbb", 9], ["F##", 7], ["D♭", 1], ["C4", 0], ["Ab3", 8]];
    for (const [name, pc] of cases) expect(nameToPc(name)).toBe(pc);
    for (const bad of ["", "H", "c", "C-", "5"]) expect(nameToPc(bad)).toBeNull();
  });

  it("writes intervals the way chord symbols do", () => {
    const cases: [string, string][] = [["P1", "R"], ["M3", "3"], ["m3", "♭3"], ["P5", "5"], ["d5", "♭5"], ["A5", "♯5"], ["m7", "♭7"], ["M7", "7"], ["M9", "9"], ["m9", "♭9"], ["A9", "♯9"], ["d7", "♭7"], ["weird", "weird"]];
    for (const [short, label] of cases) expect(intervalLabel(short)).toBe(label);
  });
});

describe("chord overlay", () => {
  it("marks the exact keys of a voicing with the root and interval labels", () => {
    const o = overlayFromChord(cmaj7 as ChordConstruct, false);
    expect(o.title).toBe("Cmaj7");
    expect([...o.marks.keys()]).toEqual(cmaj7.midi_notes);
    expect(o.marks.get(60)).toMatchObject({ role: "root", label: "R", bass: true });
    expect(o.marks.get(64)).toMatchObject({ role: "tone", label: "3" });
    expect(o.marks.get(71)).toMatchObject({ role: "tone", label: "7" });
    expect([...o.marks.values()].filter((m) => m.bass)).toHaveLength(1);
  });

  it("marks every octave when asked, and none of the wrong notes", () => {
    const o = overlayFromChord(cmaj7 as ChordConstruct, true);
    const pcs = new Set([...o.marks.keys()].map((m) => m % 12));
    expect([...pcs].sort((a, b) => a - b)).toEqual([0, 4, 7, 11]);
    expect(o.marks.get(24)?.role).toBe("root");
    expect(o.marks.get(108)?.role).toBe("root");
    expect(o.marks.size).toBeGreaterThan(25);
  });

  it("shows the bass of an inversion as the lowest key, and carries the spelling", () => {
    const o = overlayFromChord(dm7OverC as ChordConstruct, false);
    const lowest = Math.min(...o.marks.keys());
    expect(o.marks.get(lowest)).toMatchObject({ bass: true, label: "♭7" }); // C is the seventh of Dm7
    expect(o.marks.get(lowest + 2)).toMatchObject({ role: "root" });
  });

  it("marks a bass note that is not a chord tone as an extra", () => {
    const o = overlayFromChord(cOverD as ChordConstruct, false);
    const lowest = Math.min(...o.marks.keys());
    expect(o.marks.get(lowest)).toMatchObject({ role: "extra", label: "bass", bass: true });
    expect(o.marks.size).toBe(4);
  });

  it("uses the chord's own spelling for keys (Gb, not F#)", () => {
    const o = overlayFromChord(gbMajor as ChordConstruct, true);
    expect(o.spelling[6]).toBe("Gb");
    expect(o.spelling[10]).toBe("Bb");
    expect(o.spelling[1]).toBe("Db");
  });
});

describe("scale overlay", () => {
  it("marks every key of the scale with its degree, and keeps the theoretical spelling", () => {
    const o = overlayFromScale(fsharp as ScaleResult);
    expect(o.title.toLowerCase()).toContain("f# major");
    expect(o.spelling[5]).toBe("E#"); // the F key is E# in F# major
    expect(o.marks.get(66)).toMatchObject({ role: "root", label: "1" });
    expect(o.marks.get(65)).toMatchObject({ role: "scale", label: "7" });
    expect(new Set([...o.marks.keys()].map((m) => m % 12)).size).toBe(7);
  });
});

describe("two-hand voicing overlay", () => {
  it("colours left- and right-hand notes and marks the lowest as bass", () => {
    const o = overlayFromVoicing(cmaj7 as ChordConstruct, voicings as VoicingsResult);
    expect(o).not.toBeNull();
    const first = voicings.voicings[0]?.voicing;
    for (const m of first?.left ?? []) expect(o?.marks.get(m)?.hand).toBe("L");
    for (const m of first?.right ?? []) expect(o?.marks.get(m)?.hand).toBe("R");
    const bass = [...(o?.marks.entries() ?? [])].filter(([, m]) => m.bass);
    expect(bass).toHaveLength(1);
    expect(bass[0]?.[0]).toBe(Math.min(...(first?.left ?? []), ...(first?.right ?? [])));
  });

  it("returns nothing when no voicing was found", () => {
    const empty: VoicingsResult = { ...(voicings as VoicingsResult), voicings: [] };
    expect(overlayFromVoicing(cmaj7 as ChordConstruct, empty)).toBeNull();
  });
});

describe("identification overlay", () => {
  it("marks the played keys as root, tone and bass using the reading's spelling", () => {
    const first = (identifyFirst as ChordIdentify).candidates[0];
    expect(first?.symbol).toBe("C/E");
    const o = overlayFromCandidate(first!, [64, 67, 72]);
    expect(o.marks.get(72)?.role).toBe("root");
    expect(o.marks.get(64)).toMatchObject({ role: "tone", bass: true, label: "E" });
    expect(o.marks.get(67)?.role).toBe("tone");
  });

  it("shows alternative readings of the same keys differently", () => {
    const [am7, c6] = (identifyAm7 as ChordIdentify).candidates;
    const played = [57, 60, 64, 67];
    expect(overlayFromCandidate(am7!, played).marks.get(57)?.role).toBe("root");
    expect(overlayFromCandidate(c6!, played).marks.get(60)?.role).toBe("root");
    expect(overlayFromCandidate(c6!, played).marks.get(57)).toMatchObject({ role: "tone", bass: true });
  });
});
