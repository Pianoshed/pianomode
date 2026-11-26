import { describe, expect, it } from "vitest";
import { DEFAULT_PREFS, STORAGE_KEY, loadPrefs, parseLayers, parsePrefs, savePrefs } from "./prefs";

describe("preferences", () => {
  it("round-trips through storage", () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    const prefs = { ...DEFAULT_PREFS, labels: "names" as const, accidentals: "flats" as const, middleC: 3 as const, keyWidth: 30 };
    savePrefs(storage, prefs);
    expect(loadPrefs(storage)).toEqual(prefs);
    expect(store.has(STORAGE_KEY)).toBe(true);
  });

  it("falls back to defaults for missing, corrupt or hostile storage", () => {
    expect(parsePrefs(undefined)).toEqual(DEFAULT_PREFS);
    expect(parsePrefs("junk")).toEqual(DEFAULT_PREFS);
    expect(parsePrefs([1, 2])).toEqual(DEFAULT_PREFS);
    expect(loadPrefs({ getItem: () => "{not json" })).toEqual(DEFAULT_PREFS);
    expect(loadPrefs({ getItem: () => { throw new Error("blocked"); } })).toEqual(DEFAULT_PREFS);
    expect(loadPrefs(undefined)).toEqual(DEFAULT_PREFS);
  });

  it("repairs each bad field on its own and keeps the good ones", () => {
    const p = parsePrefs({ labels: "shout", accidentals: "flats", keyWidth: 9999, volume: -1, a4: 1, middleC: 7, computerBase: 50, unicode: "yes" });
    expect(p.labels).toBe(DEFAULT_PREFS.labels);
    expect(p.accidentals).toBe("flats");
    expect(p.keyWidth).toBe(DEFAULT_PREFS.keyWidth);
    expect(p.volume).toBe(DEFAULT_PREFS.volume);
    expect(p.a4).toBe(440);
    expect(p.middleC).toBe(4);
    expect(p.computerBase).toBe(DEFAULT_PREFS.computerBase);
    expect(p.unicode).toBe(DEFAULT_PREFS.unicode);
  });

  it("does not throw when storage refuses the write", () => {
    expect(() => savePrefs({ setItem: () => { throw new Error("full"); } }, DEFAULT_PREFS)).not.toThrow();
  });

  it("keeps at most three distinct valid layers", () => {
    const layers = parseLayers([
      { sound: "grand", gain: 1 },
      { sound: "grand", gain: 0.2 },
      { sound: "kazoo", gain: 1 },
      { sound: "organ", gain: 5 },
      { sound: "bells", gain: 0.4 },
      { sound: "strings", gain: 1 },
      "x",
      null,
    ]);
    expect(layers.map((l) => l.sound)).toEqual(["grand", "organ", "bells"]);
    expect(layers[1]?.gain).toBe(1); // out-of-range gain reset to the default
    expect(parseLayers([])).toEqual(DEFAULT_PREFS.layers);
    expect(parseLayers("nope")).toEqual(DEFAULT_PREFS.layers);
  });

  it("returns fresh default layers each time (no shared mutable state)", () => {
    const a = parsePrefs(undefined);
    a.layers[0]!.gain = 0.1;
    expect(parsePrefs(undefined).layers[0]?.gain).toBe(1);
  });
});
