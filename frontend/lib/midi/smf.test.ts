import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import request from "./__fixtures__/c-am-f-g.request.json";
import { MAX_FILE_BYTES, MidiError, type MidiErrorCode, parseMidi } from "./smf";

const fixture = (name: string) => new Uint8Array(readFileSync(new URL(`./__fixtures__/${name}`, import.meta.url)));

// ---- a tiny independent byte builder for odd inputs
const vlq = (n: number): number[] => {
  const out = [n & 0x7f];
  for (n >>= 7; n > 0; n >>= 7) out.push((n & 0x7f) | 0x80);
  return out.reverse();
};
const str = (s: string) => [...s].map((c) => c.charCodeAt(0));
const u32 = (n: number) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
const u16 = (n: number) => [(n >> 8) & 255, n & 255];
const header = (format = 1, tracks = 1, division = 480) => [...str("MThd"), ...u32(6), ...u16(format), ...u16(tracks), ...u16(division)];
const track = (body: number[], { end = true }: { end?: boolean } = {}) => {
  const b = end ? [...body, 0, 0xff, 0x2f, 0] : body;
  return [...str("MTrk"), ...u32(b.length), ...b];
};
const on = (delta: number, key: number, vel = 80, ch = 0) => [...vlq(delta), 0x90 | ch, key, vel];
const off = (delta: number, key: number, ch = 0) => [...vlq(delta), 0x80 | ch, key, 0];
const bytes = (...parts: number[][]) => new Uint8Array(parts.flat());
const code = (data: Uint8Array): MidiErrorCode | "none" => {
  try {
    parseMidi(data);
    return "none";
  } catch (e) {
    return e instanceof MidiError ? e.code : "none";
  }
};

describe("the two-hand fixture (written by the independent Python writer)", () => {
  const m = parseMidi(fixture("c-am-f-g.mid"));
  it("reads the header, tempo and time signature", () => {
    expect(m.format).toBe(1);
    expect(m.ppq).toBe(480);
    expect(m.tempoChanges).toEqual([{ tick: 0, bpm: 100 }]);
    expect(m.timeSignatures).toEqual([{ tick: 0, numerator: 4, denominator: 4 }]);
    expect(m.warnings).toEqual([]);
  });
  it("reads the tracks: a conductor with no notes, then two named hands", () => {
    expect(m.tracks.map((t) => [t.name, t.noteCount])).toEqual([["Conductor", 0], ["Right hand", 13], ["Left hand", 4]]);
    expect(m.tracks[1]).toMatchObject({ lowest: 57, highest: 69, channels: [0], program: 0, drumsOnly: false });
    expect(m.tracks[2]).toMatchObject({ lowest: 41, highest: 48 });
  });
  it("finds exactly the notes the writer wrote", () => {
    const wrote = request.events.filter((e) => e.kind === "note_on").map((e) => {
      const off = request.events.find((x) => x.kind === "note_off" && x.note === e.note && x.track === e.track && x.tick > e.tick)!;
      return `${e.tick}-${off.tick}:${e.note}:${e.track}:${e.velocity}`;
    });
    const read = m.notes.map((n) => `${n.startTick}-${n.endTick}:${n.note}:${n.track}:${n.velocity}`);
    expect(read.sort()).toEqual(wrote.sort());
    expect(m.notes).toHaveLength(17);
  });
  it("orders notes by start, then pitch", () => {
    for (let i = 1; i < m.notes.length; i++) {
      const a = m.notes[i - 1]!, b = m.notes[i]!;
      expect(a.startTick < b.startTick || (a.startTick === b.startTick && a.note <= b.note)).toBe(true);
      expect(b.index).toBe(i);
    }
  });
  it("ends at the last note", () => {
    expect(m.endTick).toBe(Math.max(...m.notes.map((n) => n.endTick)));
  });
});

describe("a format 0 file with running status", () => {
  const m = parseMidi(fixture("single-track.mid"));
  it("reads the same music from one track", () => {
    expect(m.format).toBe(0);
    expect(m.tracks).toHaveLength(1);
    const two = parseMidi(fixture("c-am-f-g.mid"));
    const key = (n: { startTick: number; endTick: number; note: number; velocity: number }) => `${n.startTick}-${n.endTick}:${n.note}:${n.velocity}`;
    expect(m.notes.map(key).sort()).toEqual(two.notes.map(key).sort());
    expect(m.tempoChanges).toEqual(two.tempoChanges);
  });
});

describe("files that cannot be read", () => {
  const good = fixture("c-am-f-g.mid");
  it.each<[string, Uint8Array, MidiErrorCode]>([
    ["nothing at all", new Uint8Array(), "not_midi"],
    ["plain text", new TextEncoder().encode("hello, this is not a midi file at all"), "not_midi"],
    ["a RIFF wrapper", bytes(str("RIFF"), new Array(20).fill(0)), "not_midi"],
    ["format 2", bytes(header(2, 1), track(on(0, 60).concat(off(10, 60)))), "unsupported_format"],
    ["an unknown format number", bytes(header(7, 1), track(on(0, 60).concat(off(10, 60)))), "bad_chunk"],
    ["SMPTE timing", bytes(header(1, 1, 0xe728), track(on(0, 60).concat(off(10, 60)))), "unsupported_timing"],
    ["zero ticks per beat", bytes(header(1, 1, 0), track(on(0, 60).concat(off(10, 60)))), "bad_chunk"],
    ["too many tracks", bytes(header(1, 300)), "too_many_tracks"],
    ["a header cut short", good.slice(0, 10), "not_midi"],
    ["a file with no notes", bytes(header(1, 1), track([0, 0xc0, 5])), "empty"],
    ["a header but no tracks", bytes(header(1, 1)), "empty"],
    ["data before any status byte", bytes(header(1, 1), track([0, 60, 80, 10, 60, 0])), "bad_chunk"],
    ["a time value of five bytes", bytes(header(1, 1), track([0x81, 0x81, 0x81, 0x81, 0x01, 0x90, 60, 80])), "bad_chunk"],
  ])("%s", (_name, data, expected) => {
    expect(code(data)).toBe(expected);
  });
  it("a file over the size limit", () => {
    const big = new Uint8Array(MAX_FILE_BYTES + 1);
    big.set(good);
    expect(code(big)).toBe("too_large");
  });
  it("every error has a message a person can read", () => {
    for (const data of [new Uint8Array(), bytes(header(2, 1), track([]))]) {
      try {
        parseMidi(data);
      } catch (e) {
        expect((e as Error).message.length).toBeGreaterThan(20);
      }
    }
  });
});

describe("awkward but readable input", () => {
  it("a note-on with velocity 0 ends the note", () => {
    const m = parseMidi(bytes(header(), track([...on(0, 60), ...vlq(100), 0x90, 60, 0])));
    expect(m.notes).toMatchObject([{ note: 60, startTick: 0, endTick: 100 }]);
  });
  it("pairs repeated overlapping notes first-on with first-off", () => {
    const m = parseMidi(bytes(header(), track([...on(0, 60, 70), ...on(10, 60, 90), ...off(10, 60), ...off(10, 60)])));
    expect(m.notes.map((n) => [n.startTick, n.endTick, n.velocity])).toEqual([[0, 20, 70], [10, 30, 90]]);
  });
  it("a note never released ends with its track and says so", () => {
    const m = parseMidi(bytes(header(), track([...on(0, 60), ...on(0, 64), ...off(50, 64)])));
    expect(m.notes.find((n) => n.note === 60)!.endTick).toBe(50);
    expect(m.warnings.join(" ")).toMatch(/never released/);
  });
  it("drops zero-length notes with a warning", () => {
    const m = parseMidi(bytes(header(), track([...on(0, 60), ...off(0, 60), ...on(0, 62), ...off(10, 62)])));
    expect(m.notes.map((n) => n.note)).toEqual([62]);
    expect(m.warnings.join(" ")).toMatch(/zero-length/);
  });
  it("ignores a stray note-off", () => {
    const m = parseMidi(bytes(header(), track([...off(0, 70), ...on(0, 60), ...off(10, 60)])));
    expect(m.notes).toHaveLength(1);
  });
  it("skips sysex, other controllers, and unknown chunks", () => {
    const sysex = [0, 0xf0, 3, 1, 2, 0xf7];
    const cc = [0, 0xb0, 7, 100];
    const body = [...sysex, ...cc, ...on(0, 60), ...off(10, 60)];
    const m = parseMidi(bytes(header(1, 2), [...str("XXXX"), ...u32(3), 1, 2, 3], track(body)));
    expect(m.notes).toHaveLength(1);
    expect(m.warnings.join(" ")).toMatch(/unknown chunk "XXXX"/);
  });
  it("two tempo changes on one tick: the later wins; they sort by tick", () => {
    const t = (delta: number, micros: number) => [...vlq(delta), 0xff, 0x51, 3, (micros >> 16) & 255, (micros >> 8) & 255, micros & 255];
    const m = parseMidi(bytes(header(), track([...t(0, 500_000), ...t(0, 400_000), ...t(960, 600_000), ...on(0, 60), ...off(10, 60)])));
    expect(m.tempoChanges).toEqual([{ tick: 0, bpm: 150 }, { tick: 960, bpm: 100 }]);
  });
  it("time signatures: 6/8 is read, an impossible one is ignored with a warning", () => {
    const ts = (n: number, dd: number) => [0, 0xff, 0x58, 4, n, dd, 24, 8];
    const m = parseMidi(bytes(header(), track([...ts(6, 3), ...ts(0, 2), ...on(0, 60), ...off(10, 60)])));
    expect(m.timeSignatures).toEqual([{ tick: 0, numerator: 6, denominator: 8 }]);
    expect(m.warnings.join(" ")).toMatch(/unusual time signature/);
  });
  it("notes are tied to their own channel", () => {
    const m = parseMidi(bytes(header(), track([...on(0, 60, 80, 0), ...on(0, 60, 80, 1), ...off(10, 60, 1), ...off(10, 60, 0)])));
    expect(m.notes.map((n) => [n.channel, n.endTick]).sort()).toEqual([[0, 20], [1, 10]]);
    expect(m.tracks[0]!.channels).toEqual([0, 1]);
  });
  it("a track that only uses the drum channel is flagged and warned about", () => {
    const m = parseMidi(bytes(header(1, 2), track([...on(0, 60), ...off(10, 60)]), track([...on(0, 36, 100, 9), ...off(10, 36, 9)])));
    expect(m.tracks.map((t) => t.drumsOnly)).toEqual([false, true]);
    expect(m.warnings.join(" ")).toMatch(/drums/);
  });
  it("reads track names that are not plain ASCII", () => {
    const name = new TextEncoder().encode("Piano é");
    const m = parseMidi(bytes(header(), track([0, 0xff, 3, name.length, ...name, ...on(0, 60), ...off(10, 60)])));
    expect(m.tracks[0]!.name).toBe("Piano é");
  });
  it("a track cut off mid-way keeps what could be read and says so", () => {
    const good = fixture("c-am-f-g.mid");
    const m = parseMidi(good.slice(0, 160));
    expect(m.notes.length).toBeGreaterThan(0);
    expect(m.notes.length).toBeLessThan(17);
    expect(m.warnings.join(" ")).toMatch(/cut short/);
  });
  it("a header that promises more tracks than exist is noted", () => {
    const m = parseMidi(bytes(header(1, 3), track([...on(0, 60), ...off(10, 60)])));
    expect(m.warnings.join(" ")).toMatch(/lists 3 tracks but only 1/);
  });
  it("accepts a plain Uint8Array and an ArrayBuffer alike", () => {
    const data = fixture("single-track.mid");
    expect(parseMidi(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer).notes).toHaveLength(17);
  });
});
