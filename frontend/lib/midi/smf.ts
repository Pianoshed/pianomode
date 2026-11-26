/** Standard MIDI File reader. Runs in the browser, so a file is read on the person's own device
 *  and only note events are sent for analysis.
 *
 *  Supported: formats 0 and 1, running status, note-on with velocity 0 as note-off, tempo and
 *  time-signature changes from any track, track names and the first program change.
 *  Not supported (reported as clear errors): format 2, SMPTE timing, RIFF-wrapped (.rmi) files.
 *
 *  Notes are paired first-on-with-first-off per track, channel and key, which is what the analysis
 *  service does too. A note that is never released ends with its track. */

export type MidiErrorCode =
  | "not_midi"
  | "truncated"
  | "bad_chunk"
  | "unsupported_format"
  | "unsupported_timing"
  | "too_large"
  | "too_many_tracks"
  | "empty";

export class MidiError extends Error {
  constructor(
    public code: MidiErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "MidiError";
  }
}

export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_TRACKS = 256;

export type MidiNote = {
  /** Position in `notes`, in file order. Not the analysis service's note id. */
  index: number;
  track: number;
  channel: number;
  note: number;
  velocity: number;
  startTick: number;
  endTick: number;
};
export type MidiTrack = {
  index: number;
  name: string | null;
  program: number | null;
  channels: number[];
  noteCount: number;
  lowest: number | null;
  highest: number | null;
  /** Only ever uses the General MIDI drum channel (10, which is index 9): not pitched music. */
  drumsOnly: boolean;
};
export type TempoChange = { tick: number; bpm: number };
export type TimeSignature = { tick: number; numerator: number; denominator: number };
export type ParsedMidi = {
  format: 0 | 1;
  ppq: number;
  tracks: MidiTrack[];
  notes: MidiNote[];
  tempoChanges: TempoChange[];
  timeSignatures: TimeSignature[];
  endTick: number;
  warnings: string[];
};

class Reader {
  pos: number;
  constructor(
    readonly bytes: Uint8Array,
    start: number,
    readonly end: number,
  ) {
    this.pos = start;
  }
  get done(): boolean {
    return this.pos >= this.end;
  }
  u8(): number {
    if (this.pos >= this.end) throw new MidiError("truncated", "The file ends in the middle of a track.");
    return this.bytes[this.pos++] as number;
  }
  skip(n: number): void {
    if (this.pos + n > this.end) throw new MidiError("truncated", "The file ends in the middle of a track.");
    this.pos += n;
  }
  take(n: number): Uint8Array {
    if (this.pos + n > this.end) throw new MidiError("truncated", "The file ends in the middle of a track.");
    const out = this.bytes.subarray(this.pos, this.pos + n);
    this.pos += n;
    return out;
  }
  vlq(): number {
    let value = 0;
    for (let i = 0; i < 4; i++) {
      const b = this.u8();
      value = value * 128 + (b & 0x7f);
      if ((b & 0x80) === 0) return value;
    }
    throw new MidiError("bad_chunk", "A time value in the file is longer than the MIDI format allows.");
  }
}

const u32 = (b: Uint8Array, at: number): number => ((b[at]! << 24) | (b[at + 1]! << 16) | (b[at + 2]! << 8) | b[at + 3]!) >>> 0;
const u16 = (b: Uint8Array, at: number): number => (b[at]! << 8) | b[at + 1]!;
const ascii = (b: Uint8Array, at: number, n: number): string => String.fromCharCode(...b.subarray(at, at + n));
const text = (b: Uint8Array): string => new TextDecoder("utf-8", { fatal: false }).decode(b).replace(/\0/g, "").trim();

/** Number of data bytes after a channel-message status byte. */
const dataLength = (status: number): number => {
  const kind = status & 0xf0;
  return kind === 0xc0 || kind === 0xd0 ? 1 : 2;
};

export function parseMidi(buffer: ArrayBuffer | Uint8Array): ParsedMidi {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  if (bytes.length > MAX_FILE_BYTES) {
    throw new MidiError("too_large", `This file is ${(bytes.length / 1048576).toFixed(1)} MB. MIDI files over ${MAX_FILE_BYTES / 1048576} MB are not supported.`);
  }
  if (bytes.length < 14 || ascii(bytes, 0, 4) !== "MThd") {
    const rmid = bytes.length >= 4 && ascii(bytes, 0, 4) === "RIFF";
    throw new MidiError("not_midi", rmid ? "This is a RIFF-wrapped MIDI file (.rmi). Export it as a standard .mid file." : "This is not a standard MIDI file (it should start with MThd).");
  }
  const headerLength = u32(bytes, 4);
  if (headerLength < 6 || 8 + headerLength > bytes.length) throw new MidiError("bad_chunk", "The MIDI header is damaged.");
  const format = u16(bytes, 8);
  const declaredTracks = u16(bytes, 10);
  const division = u16(bytes, 12);
  if (format === 2) throw new MidiError("unsupported_format", "Format 2 (several independent songs in one file) is not supported.");
  if (format !== 0 && format !== 1) throw new MidiError("bad_chunk", `Unknown MIDI format ${format}.`);
  if (division & 0x8000) throw new MidiError("unsupported_timing", "This file uses SMPTE time (frames per second) instead of beats. Export it with musical timing.");
  if (division === 0) throw new MidiError("bad_chunk", "The MIDI header says zero ticks per beat.");
  if (declaredTracks > MAX_TRACKS) throw new MidiError("too_many_tracks", `This file has ${declaredTracks} tracks; the limit is ${MAX_TRACKS}.`);

  const warnings: string[] = [];
  const notes: MidiNote[] = [];
  const tracks: MidiTrack[] = [];
  const tempoChanges: TempoChange[] = [];
  const timeSignatures: TimeSignature[] = [];
  let endTick = 0;
  let pos = 8 + headerLength;
  let trackIndex = 0;

  while (pos + 8 <= bytes.length && trackIndex < declaredTracks) {
    const id = ascii(bytes, pos, 4);
    const length = u32(bytes, pos + 4);
    const bodyStart = pos + 8;
    const bodyEnd = Math.min(bodyStart + length, bytes.length);
    if (bodyStart + length > bytes.length) warnings.push(`Track ${trackIndex + 1} is cut short; the notes that were readable are kept.`);
    pos = bodyStart + length;
    if (id !== "MTrk") {
      warnings.push(`Skipped an unknown chunk "${id.replace(/[^\x20-\x7e]/g, "?")}".`);
      continue;
    }

    const r = new Reader(bytes, bodyStart, bodyEnd);
    let tick = 0;
    let running = 0;
    let name: string | null = null;
    let program: number | null = null;
    const channels = new Set<number>();
    const open = new Map<number, { note: number; velocity: number; startTick: number }[]>();
    const trackNotes: MidiNote[] = [];
    const close = (channel: number, key: number, at: number) => {
      const stack = open.get(channel * 128 + key);
      const on = stack?.shift();
      if (!on) return;
      trackNotes.push({ index: -1, track: trackIndex, channel, note: key, velocity: on.velocity, startTick: on.startTick, endTick: at });
    };

    try {
      while (!r.done) {
        tick += r.vlq();
        let status = r.u8();
        if (status < 0x80) {
          if (running === 0) throw new MidiError("bad_chunk", `Track ${trackIndex + 1} has data with no status byte.`);
          r.pos--; // running status: this byte is data for the previous status
          status = running;
        }
        if (status === 0xff) {
          const type = r.u8();
          const data = r.take(r.vlq());
          if (type === 0x2f) break;
          if (type === 0x03 && name === null) name = text(data) || null;
          else if (type === 0x51 && data.length === 3) {
            const micros = (data[0]! << 16) | (data[1]! << 8) | data[2]!;
            if (micros > 0) tempoChanges.push({ tick, bpm: 60_000_000 / micros });
          } else if (type === 0x58 && data.length >= 2) {
            const denominator = 2 ** data[1]!;
            if (data[0]! >= 1 && [1, 2, 4, 8, 16, 32].includes(denominator)) timeSignatures.push({ tick, numerator: data[0]!, denominator });
            else warnings.push(`Ignored an unusual time signature at tick ${tick}.`);
          }
          continue;
        }
        if (status === 0xf0 || status === 0xf7) {
          r.skip(r.vlq());
          running = 0;
          continue;
        }
        if (status >= 0xf1) {
          warnings.push(`Skipped an unexpected system message in track ${trackIndex + 1}.`);
          running = 0;
          continue;
        }
        running = status;
        const channel = status & 0x0f;
        const kind = status & 0xf0;
        const d1 = r.u8();
        const d2 = dataLength(status) === 2 ? r.u8() : 0;
        if (kind === 0x90 && d2 > 0) {
          channels.add(channel);
          const stack = open.get(channel * 128 + d1) ?? [];
          stack.push({ note: d1, velocity: d2, startTick: tick });
          open.set(channel * 128 + d1, stack);
        } else if (kind === 0x80 || kind === 0x90) {
          close(channel, d1, tick);
        } else if (kind === 0xc0 && program === null) {
          program = d1;
        }
      }
    } catch (e) {
      if (!(e instanceof MidiError) || e.code !== "truncated") throw e;
      warnings.push(`Track ${trackIndex + 1} is cut short; the notes that were readable are kept.`);
    }

    let unreleased = 0;
    for (const [k, stack] of open) {
      for (const on of stack) {
        unreleased++;
        trackNotes.push({ index: -1, track: trackIndex, channel: Math.floor(k / 128), note: on.note, velocity: on.velocity, startTick: on.startTick, endTick: Math.max(tick, on.startTick) });
      }
    }
    if (unreleased) warnings.push(`${unreleased} note${unreleased === 1 ? " was" : "s were"} never released in track ${trackIndex + 1}; they end with the track.`);
    const kept = trackNotes.filter((n) => n.endTick > n.startTick);
    const zero = trackNotes.length - kept.length;
    if (zero) warnings.push(`${zero} zero-length note${zero === 1 ? "" : "s"} in track ${trackIndex + 1} ignored.`);

    for (const n of kept) {
      notes.push(n);
      endTick = Math.max(endTick, n.endTick);
    }
    endTick = Math.max(endTick, tick);
    const pitches = kept.map((n) => n.note);
    const chans = [...channels].sort((a, b) => a - b);
    tracks.push({
      index: trackIndex,
      name,
      program,
      channels: chans,
      noteCount: kept.length,
      lowest: pitches.length ? Math.min(...pitches) : null,
      highest: pitches.length ? Math.max(...pitches) : null,
      drumsOnly: chans.length > 0 && chans.every((c) => c === 9),
    });
    trackIndex++;
  }

  if (trackIndex < declaredTracks) warnings.push(`The header lists ${declaredTracks} tracks but only ${trackIndex} could be read.`);
  if (notes.length === 0) throw new MidiError("empty", "This file contains no notes.");
  // One list in time order (the analysis service orders notes the same way).
  notes.sort((a, b) => a.startTick - b.startTick || a.note - b.note || a.track - b.track || a.channel - b.channel || a.endTick - b.endTick);
  notes.forEach((n, i) => {
    n.index = i;
  });
  for (const t of tracks) if (t.drumsOnly) warnings.push(`Track ${t.index + 1}${t.name ? ` (${t.name})` : ""} is drums, so it is muted. Drum notes are not pitches.`);

  const byTick = <T extends { tick: number }>(items: T[]): T[] => {
    const last = new Map<number, T>();
    for (const i of items) last.set(i.tick, i); // two changes at one tick: the later one wins
    return [...last.values()].sort((a, b) => a.tick - b.tick);
  };
  return { format: format as 0 | 1, ppq: division, tracks, notes, tempoChanges: byTick(tempoChanges), timeSignatures: byTick(timeSignatures), endTick, warnings };
}
