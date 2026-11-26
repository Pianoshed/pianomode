import { describe, expect, it } from "vitest";
import { type CorrectionsInput, MAX_CORRECTIONS_BYTES, corrections, exportTracks, parseCorrections } from "./export";
import { type MidiNote, type ParsedMidi, parseMidi } from "./smf";
import type { TrackState } from "./studio";
import { writeMidi } from "./writer";

const note = (index: number, track: number, n: number, start: number, end = start + 480, channel = 0): MidiNote => ({ index, track, channel, note: n, velocity: 90, startTick: start, endTick: end });
const parsed = (notes: MidiNote[], names: Record<number, string> = {}): ParsedMidi => ({
  format: 1, ppq: 480, notes, endTick: 4800,
  tracks: [0, 1, 2].map((i) => ({ index: i, name: names[i] ?? null, program: null, channels: [0], noteCount: notes.filter((n) => n.track === i).length, lowest: null, highest: null, drumsOnly: false })),
  tempoChanges: [{ tick: 0, bpm: 120 }], timeSignatures: [{ tick: 0, numerator: 4, denominator: 4 }], warnings: [],
});
const st = (o: Partial<TrackState> = {}): TrackState => ({ hand: null, muted: false, solo: false, ...o });

describe("MIDI writer", () => {
  it("writes a file the reader reads back the same", () => {
    const bytes = writeMidi({
      ppq: 480,
      tempoChanges: [{ tick: 0, bpm: 120 }, { tick: 960, bpm: 90 }],
      timeSignatures: [{ tick: 0, numerator: 3, denominator: 4 }, { tick: 1440, numerator: 6, denominator: 8 }],
      tracks: [
        { name: "Right hand", notes: [{ note: 72, velocity: 100, startTick: 0, endTick: 480, channel: 0 }, { note: 74, velocity: 80, startTick: 480, endTick: 960, channel: 0 }] },
        { name: "Left hand", notes: [{ note: 48, velocity: 70, startTick: 0, endTick: 1920, channel: 1 }] },
      ],
    });
    const back = parseMidi(bytes);
    expect(back.format).toBe(1);
    expect(back.ppq).toBe(480);
    expect(back.notes.map((n) => [n.note, n.startTick, n.endTick, n.velocity, n.channel]).sort()).toEqual([[48, 0, 1920, 70, 1], [72, 0, 480, 100, 0], [74, 480, 960, 80, 0]]);
    expect(back.tracks.map((t) => t.name).filter(Boolean)).toEqual(expect.arrayContaining(["Right hand", "Left hand"]));
    expect(back.tempoChanges.map((t) => [t.tick, Math.round(t.bpm)])).toEqual([[0, 120], [960, 90]]);
    expect(back.timeSignatures.map((s) => [s.tick, s.numerator, s.denominator])).toEqual([[0, 3, 4], [1440, 6, 8]]);
  });

  it("ends a note before the next one starts on the same pitch", () => {
    const back = parseMidi(writeMidi({ ppq: 96, tempoChanges: [], timeSignatures: [], tracks: [{ name: "x", notes: [
      { note: 60, velocity: 90, startTick: 0, endTick: 96, channel: 0 }, { note: 60, velocity: 90, startTick: 96, endTick: 192, channel: 0 }] }] }));
    expect(back.notes.map((n) => [n.startTick, n.endTick])).toEqual([[0, 96], [96, 192]]);
  });

  it("keeps odd values legal", () => {
    const back = parseMidi(writeMidi({ ppq: 480, tempoChanges: [], timeSignatures: [], tracks: [{ name: "x", notes: [{ note: 200, velocity: 0, startTick: 10, endTick: 5, channel: 40 }] }] }));
    expect(back.notes).toHaveLength(1);
    expect(back.notes[0]!.velocity).toBeGreaterThanOrEqual(1);
    expect(back.notes[0]!.endTick).toBeGreaterThan(back.notes[0]!.startTick);
  });

  it("refuses an unusable resolution", () => {
    for (const ppq of [0, -1, 1.5, 40000]) expect(() => writeMidi({ ppq, tempoChanges: [], timeSignatures: [], tracks: [] })).toThrow(RangeError);
  });
});

describe("exportTracks", () => {
  const notes = [note(0, 0, 72, 0), note(1, 1, 48, 0), note(2, 2, 60, 0)];
  const p = parsed(notes, { 0: "Melody", 1: "Bass" });

  it("names tracks, labelling the assigned hand", () => {
    const out = exportTracks(p, [], { 0: st({ hand: "R" }), 1: st({ hand: "L" }), 2: st() }, new Map());
    expect(out.map((t) => t.name)).toEqual(["Melody (right hand)", "Bass (left hand)", "Track 3"]);
  });

  it("leaves out muted tracks unless asked, and honours solo", () => {
    const states = { 0: st(), 1: st({ muted: true }), 2: st() };
    expect(exportTracks(p, [], states, new Map()).map((t) => t.name)).toEqual(["Melody", "Track 3"]);
    expect(exportTracks(p, [], states, new Map(), true)).toHaveLength(3);
    expect(exportTracks(p, [], { 0: st(), 1: st({ solo: true }), 2: st() }, new Map()).map((t) => t.name)).toEqual(["Bass"]);
  });

  it("applies merges and splits", () => {
    const merged = exportTracks(p, [{ type: "merge", from: [1], into: 0 }], { 0: st(), 1: st(), 2: st() }, new Map());
    expect(merged.find((t) => t.name === "Melody")!.notes.map((n) => n.note).sort()).toEqual([48, 72]);
    expect(merged.some((t) => t.name === "Bass")).toBe(false);
  });

  it("gathers hand corrections into two extra tracks", () => {
    const out = exportTracks(p, [], { 0: st(), 1: st(), 2: st() }, new Map([["0:72:0", "L" as const], ["0:48:0", "R" as const]]));
    expect(out.map((t) => t.name)).toEqual(["Track 3", "Left hand (corrected)", "Right hand (corrected)"]);
    expect(out[1]!.notes[0]!.note).toBe(72);
    expect(out[2]!.notes[0]!.note).toBe(48);
  });

  it("returns nothing when everything is muted", () => {
    expect(exportTracks(p, [], { 0: st({ muted: true }), 1: st({ muted: true }), 2: st({ muted: true }) }, new Map())).toEqual([]);
  });
});

describe("corrections file", () => {
  const p = parsed([note(0, 0, 60, 0), note(1, 1, 48, 0)]);
  const input: CorrectionsInput = {
    fileName: "song.mid", parsed: p, edits: [{ type: "merge", from: [1], into: 0 }, { type: "split", track: 0, pitch: 60, into: 2 }],
    trackStates: { 0: st({ hand: "R" }), 1: st({ muted: true, solo: false }) }, handEdits: new Map([["0:60:0", "L" as const]]),
    key: { tonic: "C", mode: "major" }, grid: "beat", prefer: "flats",
  };
  const text = JSON.stringify(corrections(input));

  it("restores exactly what was saved", () => {
    const r = parseCorrections(text, p);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.data.edits).toEqual(input.edits);
    expect(r.data.trackStates).toEqual(input.trackStates);
    expect(r.data.handEdits).toEqual([["0:60:0", "L"]]);
    expect(r.data).toMatchObject({ key: { tonic: "C", mode: "major" }, grid: "beat", prefer: "flats" });
  });

  it("refuses corrections saved for a different file", () => {
    const other = parsed([note(0, 0, 60, 0)]);
    const r = parseCorrections(text, other);
    expect(r).toMatchObject({ ok: false });
    expect((r as { error: string }).error).toMatch(/different MIDI file/);
  });

  it.each([
    ["not json", "{nope"],
    ["wrong version", JSON.stringify({ ...corrections(input), version: 9 })],
    ["bad edit", JSON.stringify({ ...corrections(input), edits: [{ type: "merge", from: [999], into: 0 }] })],
    ["unknown edit", JSON.stringify({ ...corrections(input), edits: [{ type: "explode" }] })],
    ["bad track hand", JSON.stringify({ ...corrections(input), trackStates: { 0: { hand: "X", muted: false, solo: false } } })],
    ["bad track number", JSON.stringify({ ...corrections(input), trackStates: { 999: { hand: null, muted: false, solo: false } } })],
    ["bad hand key", JSON.stringify({ ...corrections(input), handEdits: [["<script>", "L"]] })],
    ["bad hand value", JSON.stringify({ ...corrections(input), handEdits: [["0:60:0", "X"]] })],
    ["bad key", JSON.stringify({ ...corrections(input), key: { tonic: "H", mode: "major" } })],
    ["bad grid", JSON.stringify({ ...corrections(input), grid: "half_beat" })],
    ["array instead of object", "[]"],
  ])("rejects %s", (_name, bad) => {
    expect(parseCorrections(bad, p)).toMatchObject({ ok: false });
  });

  it("rejects a file that is too large", () => {
    expect(parseCorrections(" ".repeat(MAX_CORRECTIONS_BYTES + 1), p)).toMatchObject({ ok: false });
  });
});
