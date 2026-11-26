import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { type ParsedMidi, parseMidi } from "@/lib/midi/smf";
import { bytesToBase64 } from "@/lib/library/base64";
import { restoreMidiProject, serializeMidiProject } from "@/lib/library/midiProject";

const bytes = readFileSync(new URL("../midi/__fixtures__/c-am-f-g.mid", import.meta.url));
const parsed: ParsedMidi = parseMidi(new Uint8Array(bytes));
const firstTrack = parsed.tracks.find((t) => t.noteCount > 0)!.index;

describe("MIDI project settings", () => {
  it("come back exactly as saved", () => {
    const settings = {
      edits: [],
      trackStates: { [firstTrack]: { hand: "R" as const, muted: false, solo: true } },
      fromBar: 1,
      grid: "bar" as const,
      prefer: "flats" as const,
      keyChoice: { tonic: "Bb", mode: "minor" },
      handEdits: new Map([["n1", "L" as const]]),
    };
    const json = JSON.parse(JSON.stringify(serializeMidiProject(settings))); // as the server returns it
    const back = restoreMidiProject(json, parsed);
    expect(back.edits).toEqual([]);
    expect(back.trackStates[firstTrack]).toEqual({ hand: "R", muted: false, solo: true });
    expect([back.fromBar, back.grid, back.prefer, back.keyChoice]).toEqual([1, "bar", "flats", { tonic: "Bb", mode: "minor" }]);
    expect([...back.handEdits]).toEqual([["n1", "L"]]);
    expect(json.v).toBe(1);
  });

  it("falls back to the normal defaults for empty, missing or nonsense data", () => {
    for (const junk of [null, undefined, 5, "text", [], {}, { grid: 7, prefer: {}, fromBar: -3, keyChoice: "C" }]) {
      const s = restoreMidiProject(junk, parsed);
      expect([s.grid, s.prefer, s.fromBar, s.keyChoice, s.edits.length, s.handEdits.size]).toEqual(["beat", "sharps", 0, null, 0, 0]);
      expect(s.trackStates[firstTrack]).toEqual({ hand: null, muted: false, solo: false });
    }
  });

  it("drops invalid pieces one by one without losing the rest", () => {
    const s = restoreMidiProject(
      {
        grid: "half_bar",
        keyChoice: { tonic: "H#", mode: "major" }, // not a note
        fromBar: 99_999_999, // beyond the music
        trackStates: { [firstTrack]: { hand: "middle", muted: "yes", solo: true } },
        handEdits: [["ok", "R"], ["bad", "X"], "junk", [1, "L"]],
      },
      parsed,
    );
    expect(s.grid).toBe("half_bar");
    expect(s.keyChoice).toBeNull();
    expect(s.fromBar).toBe(0);
    expect(s.trackStates[firstTrack]).toEqual({ hand: null, muted: false, solo: true });
    expect([...s.handEdits]).toEqual([["ok", "R"]]);
  });

  it("ignores edits that do not fit the file or are malformed", () => {
    expect(restoreMidiProject({ edits: [{ type: "merge", from: [firstTrack], into: firstTrack }] }, parsed).edits).toEqual([]); // merge into itself throws
    expect(restoreMidiProject({ edits: [{ type: "explode" }] }, parsed).edits).toEqual([]);
    expect(restoreMidiProject({ edits: "nope" }, parsed).edits).toEqual([]);
    expect(restoreMidiProject({ edits: [{ type: "split", track: firstTrack, pitch: 60, into: 200 }] }, parsed).edits).toHaveLength(1);
  });

  it("gives every track with notes a state, even ones the save did not mention", () => {
    const s = restoreMidiProject({ trackStates: {} }, parsed);
    expect(Object.keys(s.trackStates).map(Number)).toEqual(parsed.tracks.filter((t) => t.noteCount > 0).map((t) => t.index));
  });
});

describe("bytesToBase64", () => {
  it("matches Node's own encoding, including for files bigger than one chunk", () => {
    const big = new Uint8Array(100_000).map((_, i) => (i * 31) % 256);
    expect(bytesToBase64(big.buffer)).toBe(Buffer.from(big).toString("base64"));
    expect(bytesToBase64(new Uint8Array(0).buffer)).toBe("");
    expect(bytesToBase64(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer)).toBe(bytes.toString("base64"));
  });
});

import { restoreAudioProject, sameRecording, serializeAudioProject } from "@/lib/library/audioProject";
import { progressionFromQuery, progressionHref, restoreProgression, serializeProgression } from "@/lib/library/progression";

describe("audio project settings", () => {
  const base = { decode: { set: "triads" as const, stability: 0.7, minDuration: 0.6 }, keyChoice: { tonic: "F#", mode: "minor" }, prefer: "flats" as const, ambiguity: "more" as const, fileName: "take3.wav", duration: 187.2, summary: { chords: 41, key: "F# minor" } };

  it("round-trips including corrections", () => {
    const corrections = [{ op: "relabel" as const, index: 3, label: "Am7" }, { op: "retime" as const, index: 4, start: 10.5, end: 12 }, { op: "add" as const, start: 1, end: 2, label: "C" }, { op: "delete" as const, index: 9 }];
    const back = restoreAudioProject(JSON.parse(JSON.stringify(serializeAudioProject({ ...base, corrections }))));
    expect(back).toMatchObject({ ...base, corrections });
  });
  it("uses defaults for nonsense and drops bad corrections one by one", () => {
    const s = restoreAudioProject({ decode: { set: "ninths", stability: 9 }, ambiguity: "wild", prefer: 3, corrections: [{ op: "relabel", index: -1, label: "C" }, { op: "retime", index: 1, start: 5, end: 4 }, { op: "delete", index: 2 }, "x"] });
    expect([s.decode.set, s.decode.stability, s.ambiguity, s.prefer]).toEqual(["sevenths", 0.5, "normal", "sharps"]);
    expect(s.corrections).toEqual([{ op: "delete", index: 2 }]);
    expect(restoreAudioProject(null).corrections).toEqual([]);
  });
  it("only applies corrections to a recording of about the same length", () => {
    const s = restoreAudioProject({ duration: 100 });
    expect(sameRecording(s, 100.8)).toBe(true);
    expect(sameRecording(s, 140)).toBe(false);
    expect(sameRecording(restoreAudioProject({}), 5)).toBe(true);
  });
});

describe("progression settings", () => {
  it("round-trips through the saved data and the page address", () => {
    const s = { slug: "ii-v-i", tonic: "Bb", level: "advanced" as const, hands: "L" as const, tempo: 96 };
    expect(restoreProgression(JSON.parse(JSON.stringify(serializeProgression(s))))).toEqual(s);
    const href = progressionHref(s);
    expect(href.startsWith("/progressions/ii-v-i?")).toBe(true);
    const q = Object.fromEntries(new URL(href, "http://x").searchParams);
    expect(progressionFromQuery(q)).toEqual({ tonic: "Bb", level: "advanced", hands: "L", tempo: 96 });
  });
  it("refuses saves without a usable movement and clamps the rest", () => {
    expect(restoreProgression({ slug: "../etc" })).toBeNull();
    expect(restoreProgression(null)).toBeNull();
    expect(restoreProgression({ slug: "ok", tempo: 9000, level: "godlike", tonic: "Z" })).toEqual({ slug: "ok", tonic: null, level: "intermediate", hands: "both", tempo: 200 });
  });
  it("ignores bad address parameters", () => {
    expect(progressionFromQuery({ key: "Q", level: "nope", hands: "x", tempo: "abc" })).toEqual({});
    expect(progressionFromQuery({})).toEqual({});
  });
});
