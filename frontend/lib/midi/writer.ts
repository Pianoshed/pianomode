/** Writes a Standard MIDI File (format 1): a tempo-map track, then one track per part. */

import type { TempoChange, TimeSignature } from "./smf";

export type OutNote = { note: number; velocity: number; startTick: number; endTick: number; channel: number };
export type OutTrack = { name: string; notes: OutNote[] };
export type WriteInput = { ppq: number; tempoChanges: readonly TempoChange[]; timeSignatures: readonly TimeSignature[]; tracks: readonly OutTrack[] };

const MAX_TICK = 0x0fffffff; // a variable-length time value holds 28 bits

const vlq = (n: number): number[] => {
  const out = [n & 0x7f];
  for (let v = Math.floor(n / 128); v > 0; v = Math.floor(v / 128)) out.unshift((v & 0x7f) | 0x80);
  return out;
};
const text = (s: string): number[] => [...new TextEncoder().encode(s)];
const meta = (type: number, data: number[]): number[] => [0xff, type, ...vlq(data.length), ...data];
const u32 = (n: number): number[] => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
const chunk = (id: string, body: number[]): number[] => [...text(id), ...u32(body.length), ...body];

type Ev = { tick: number; order: number; bytes: number[] };

function track(events: Ev[]): number[] {
  events.sort((a, b) => a.tick - b.tick || a.order - b.order);
  const body: number[] = [];
  let last = 0;
  for (const e of events) {
    body.push(...vlq(e.tick - last), ...e.bytes);
    last = e.tick;
  }
  body.push(...vlq(0), ...meta(0x2f, []));
  return chunk("MTrk", body);
}

export function writeMidi(input: WriteInput): Uint8Array {
  const { ppq } = input;
  if (!Number.isInteger(ppq) || ppq < 1 || ppq > 32767) throw new RangeError("Ticks per quarter note must be 1 to 32767.");
  const conductor: Ev[] = [{ tick: 0, order: 0, bytes: meta(0x03, text("Tempo map")) }];
  for (const t of input.tempoChanges) {
    const micros = Math.round(60_000_000 / Math.min(1000, Math.max(1, t.bpm)));
    conductor.push({ tick: Math.min(MAX_TICK, Math.max(0, t.tick)), order: 1, bytes: meta(0x51, [(micros >> 16) & 255, (micros >> 8) & 255, micros & 255]) });
  }
  for (const s of input.timeSignatures) {
    const power = Math.max(0, Math.round(Math.log2(s.denominator)));
    conductor.push({ tick: Math.min(MAX_TICK, Math.max(0, s.tick)), order: 1, bytes: meta(0x58, [Math.min(255, s.numerator), power, 24, 8]) });
  }
  const chunks = [track(conductor)];
  for (const t of input.tracks) {
    const events: Ev[] = [{ tick: 0, order: 0, bytes: meta(0x03, text(t.name)) }];
    for (const n of t.notes) {
      const start = Math.min(MAX_TICK, Math.max(0, Math.round(n.startTick)));
      const end = Math.min(MAX_TICK, Math.max(start + 1, Math.round(n.endTick)));
      const ch = Math.min(15, Math.max(0, n.channel));
      const vel = Math.min(127, Math.max(1, Math.round(n.velocity)));
      events.push({ tick: start, order: 3, bytes: [0x90 | ch, n.note & 127, vel] }); // note-on after any note-off at the same tick
      events.push({ tick: end, order: 2, bytes: [0x80 | ch, n.note & 127, 0] });
    }
    chunks.push(track(events));
  }
  const header = chunk("MThd", [0, 1, (chunks.length >> 8) & 255, chunks.length & 255, (ppq >> 8) & 255, ppq & 255]);
  return Uint8Array.from([...header, ...chunks.flat()]);
}
