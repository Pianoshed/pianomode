import { describe, expect, it } from "vitest";
import {
  BLACK_HEIGHT,
  BLACK_KEYS,
  HIGHEST_MIDI,
  KEYS,
  LOWEST_MIDI,
  WHITE_COUNT,
  WHITE_KEYS,
  accessibleName,
  keyFor,
  midiFromPoint,
  midiToFrequency,
  noteLabel,
  octaveFor,
  pitchClassName,
  velocityFromY,
} from "./keys";

describe("88-key layout", () => {
  it("has 88 keys: 52 white and 36 black, from A0 to C8", () => {
    expect(KEYS).toHaveLength(88);
    expect(WHITE_COUNT).toBe(52);
    expect(BLACK_KEYS).toHaveLength(36);
    expect(KEYS[0]?.midi).toBe(LOWEST_MIDI);
    expect(KEYS.at(-1)?.midi).toBe(HIGHEST_MIDI);
    expect(keyFor(21)?.octave).toBe(0);
    expect(keyFor(108)?.octave).toBe(8);
  });

  it("puts white keys one unit apart and each black key between its neighbours", () => {
    WHITE_KEYS.forEach((k, i) => expect(k.x).toBe(i));
    for (const b of BLACK_KEYS) {
      const below = keyFor(b.midi - 1);
      const above = keyFor(b.midi + 1);
      expect(below && !below.black && above && !above.black).toBe(true);
      const centre = b.x + b.width / 2;
      expect(centre).toBeGreaterThan((below?.x ?? 0) + 0.5);
      expect(centre).toBeLessThan((above?.x ?? 0) + 0.5);
    }
  });

  it("has no black key between E-F or B-C", () => {
    for (const k of KEYS) if (k.pc === 4 || k.pc === 11) expect(keyFor(k.midi + 1)?.black ?? false).toBe(false);
  });
});

describe("hit testing", () => {
  it("finds white keys across the full width", () => {
    expect(midiFromPoint(0.5, 0.95)).toBe(21);
    expect(midiFromPoint(51.5, 0.95)).toBe(108);
    expect(midiFromPoint(23.5, 0.9)).toBe(60); // middle C is the 24th white key (index 23)
  });

  it("finds black keys only in their upper part", () => {
    const cs4 = keyFor(61);
    expect(cs4?.black).toBe(true);
    const x = (cs4?.x ?? 0) + (cs4?.width ?? 0) / 2;
    expect(midiFromPoint(x, 0.2)).toBe(61);
    expect(midiFromPoint(x, BLACK_HEIGHT + 0.05)).not.toBe(61); // below the black key: the white key
    expect([60, 62]).toContain(midiFromPoint(x, BLACK_HEIGHT + 0.05));
  });

  it("every key can be hit at its own centre", () => {
    for (const k of KEYS) {
      const y = k.black ? BLACK_HEIGHT / 2 : 0.9;
      expect(midiFromPoint(k.x + k.width / 2, y)).toBe(k.midi);
    }
  });

  it("returns null outside the keyboard", () => {
    for (const [x, y] of [[-0.1, 0.5], [WHITE_COUNT, 0.5], [3, -0.1], [3, 1.1], [Number.NaN, 0.5]] as const)
      expect(midiFromPoint(x, y)).toBeNull();
  });
});

describe("velocity", () => {
  it("is quieter near the top of a key and louder toward the bottom, always 1-127", () => {
    expect(velocityFromY(0.05, false)).toBeLessThan(velocityFromY(0.95, false));
    expect(velocityFromY(0, false)).toBeGreaterThanOrEqual(1);
    expect(velocityFromY(1, false)).toBeLessThanOrEqual(127);
    expect(velocityFromY(BLACK_HEIGHT, true)).toBe(velocityFromY(1, false));
    expect(velocityFromY(5, false)).toBe(127);
    expect(velocityFromY(-5, false)).toBe(36);
  });
});

describe("frequency", () => {
  it("A4 is 440 Hz, an octave doubles it, and the tuning reference is configurable", () => {
    expect(midiToFrequency(69)).toBe(440);
    expect(midiToFrequency(81)).toBeCloseTo(880, 9);
    expect(midiToFrequency(60)).toBeCloseTo(261.6256, 3);
    expect(midiToFrequency(69, 432)).toBe(432);
  });
});

describe("labels", () => {
  const base = { accidentals: "sharps" as const };
  it("labels only the C keys with their octave by default mode 'c'", () => {
    expect(noteLabel(60, { ...base, mode: "c" })).toBe("C4");
    expect(noteLabel(61, { ...base, mode: "c" })).toBe("");
    expect(noteLabel(24, { ...base, mode: "c" })).toBe("C1");
  });

  it("honours the sharps/flats preference and the octave convention", () => {
    expect(noteLabel(61, { ...base, mode: "names" })).toBe("C#");
    expect(noteLabel(61, { accidentals: "flats", mode: "names" })).toBe("Db");
    expect(noteLabel(60, { ...base, mode: "names-octave", middleC: 3 })).toBe("C3");
    expect(noteLabel(60, { ...base, mode: "names-octave", middleC: 5 })).toBe("C5");
    expect(noteLabel(60, { ...base, mode: "none" })).toBe("");
    expect(pitchClassName(-1, "sharps")).toBe("B");
  });

  it("uses the engine's spelling over the preference, including theoretical names", () => {
    const spelling = { 3: "D#", 5: "E#", 11: "Cb" };
    expect(noteLabel(63, { accidentals: "flats", mode: "names", spelling })).toBe("D#");
    expect(noteLabel(65, { ...base, mode: "names", spelling })).toBe("E#");
    expect(noteLabel(61, { ...base, mode: "names", spelling })).toBe("C#"); // no override: preference
  });

  it("puts B# and Cb in the octave their spelling implies", () => {
    expect(octaveFor(60, "B#")).toBe(3); // B#3 sounds as C4
    expect(octaveFor(59, "Cb")).toBe(4); // Cb4 sounds as B3
    expect(octaveFor(60, "C")).toBe(4);
    expect(noteLabel(60, { ...base, mode: "names-octave", spelling: { 0: "B#" } })).toBe("B#3");
  });

  it("can show real sharp and flat signs", () => {
    expect(noteLabel(61, { accidentals: "flats", mode: "names-octave", unicode: true })).toBe("D♭4");
    expect(noteLabel(61, { ...base, mode: "names", unicode: true })).toBe("C♯");
    expect(noteLabel(71, { ...base, mode: "names", unicode: true })).toBe("B"); // the letter B is not a flat
    expect(noteLabel(60, { ...base, mode: "names", unicode: true, spelling: { 0: "Bbb" } })).toBe("B𝄫");
  });

  it("gives screen readers words, not symbols", () => {
    expect(accessibleName(61, base)).toBe("C sharp 4");
    expect(accessibleName(70, { accidentals: "flats" })).toBe("B flat 4");
    expect(accessibleName(71, base)).toBe("B 4");
  });
});
