import { describe, expect, it } from "vitest";
import { parseMidiMessage } from "./midiInput";

describe("MIDI messages", () => {
  it("reads note on and off on any channel", () => {
    expect(parseMidiMessage([0x90, 60, 100])).toEqual({ type: "on", note: 60, velocity: 100 });
    expect(parseMidiMessage([0x9f, 72, 1])).toEqual({ type: "on", note: 72, velocity: 1 });
    expect(parseMidiMessage([0x80, 60, 64])).toEqual({ type: "off", note: 60 });
    expect(parseMidiMessage([0x83, 60, 0])).toEqual({ type: "off", note: 60 });
  });

  it("treats note-on with velocity 0 as note-off", () => {
    expect(parseMidiMessage([0x90, 60, 0])).toEqual({ type: "off", note: 60 });
  });

  it("reads the sustain pedal", () => {
    expect(parseMidiMessage([0xb0, 64, 127])).toEqual({ type: "sustain", on: true });
    expect(parseMidiMessage([0xb0, 64, 63])).toEqual({ type: "sustain", on: false });
    expect(parseMidiMessage([0xb0, 7, 100])).toEqual({ type: "other" });
  });

  it("ignores everything else and short or empty messages", () => {
    expect(parseMidiMessage([0xe0, 0, 64])).toEqual({ type: "other" });
    expect(parseMidiMessage([0xf8])).toEqual({ type: "other" });
    expect(parseMidiMessage([])).toEqual({ type: "other" });
    expect(parseMidiMessage([0x90])).toEqual({ type: "other" });
    expect(parseMidiMessage([0x90, 60])).toEqual({ type: "other" });
  });
});
