/** Playing from a MIDI keyboard through the Web MIDI API (Chrome, Edge and some others; not Safari). */

export type MidiMessage =
  | { type: "on"; note: number; velocity: number }
  | { type: "off"; note: number }
  | { type: "sustain"; on: boolean }
  | { type: "other" };

/** Decode one raw MIDI message. A note-on with velocity 0 is a note-off, as the MIDI spec says. */
export function parseMidiMessage(data: ArrayLike<number>): MidiMessage {
  const status = data[0];
  const a = data[1];
  const b = data[2];
  if (status === undefined || a === undefined) return { type: "other" };
  const kind = status & 0xf0;
  if (kind === 0x90 && b !== undefined) return b > 0 ? { type: "on", note: a, velocity: b } : { type: "off", note: a };
  if (kind === 0x80) return { type: "off", note: a };
  if (kind === 0xb0 && a === 64 && b !== undefined) return { type: "sustain", on: b >= 64 };
  return { type: "other" };
}

export type MidiHandlers = {
  onMessage: (m: MidiMessage) => void;
  onStatus: (s: MidiStatus) => void;
};
export type MidiStatus =
  | { state: "unsupported" }
  | { state: "denied" }
  | { state: "ready"; devices: string[] };

/** Start listening to every MIDI input. Returns a function that stops listening. */
export async function connectMidi(handlers: MidiHandlers): Promise<() => void> {
  if (typeof navigator === "undefined" || typeof navigator.requestMIDIAccess !== "function") {
    handlers.onStatus({ state: "unsupported" });
    return () => undefined;
  }
  let access: MIDIAccess;
  try {
    access = await navigator.requestMIDIAccess();
  } catch {
    handlers.onStatus({ state: "denied" });
    return () => undefined;
  }
  const listener = (e: MIDIMessageEvent) => {
    if (e.data) handlers.onMessage(parseMidiMessage(e.data));
  };
  const attach = () => {
    const names: string[] = [];
    access.inputs.forEach((input) => {
      input.onmidimessage = listener;
      names.push(input.name ?? "MIDI device");
    });
    handlers.onStatus({ state: "ready", devices: names });
  };
  attach();
  access.onstatechange = attach;
  return () => {
    access.onstatechange = null;
    access.inputs.forEach((input) => {
      input.onmidimessage = null;
    });
  };
}
