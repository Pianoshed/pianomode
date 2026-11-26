import { describe, expect, it } from "vitest";
import { midiForCode, shouldIgnoreKeyEvent, spaceBelongsToControl } from "./computerKeys";

describe("computer keyboard", () => {
  it("lays two rows out like a piano starting at the chosen base", () => {
    expect(midiForCode("KeyZ", 48)).toBe(48); // C
    expect(midiForCode("KeyS", 48)).toBe(49); // C#
    expect(midiForCode("KeyX", 48)).toBe(50);
    expect(midiForCode("KeyM", 48)).toBe(59); // B
    expect(midiForCode("KeyQ", 48)).toBe(60); // upper row: next C
    expect(midiForCode("Digit2", 48)).toBe(61);
    expect(midiForCode("KeyW", 48)).toBe(62);
  });

  it("repeats the same note where the rows overlap rather than shifting", () => {
    expect(midiForCode("Comma", 48)).toBe(60);
    expect(midiForCode("KeyQ", 48)).toBe(60);
  });

  it("ignores keys that are not piano keys, and notes that fall off the keyboard", () => {
    expect(midiForCode("Space", 48)).toBeNull();
    expect(midiForCode("KeyA", 48)).toBeNull();
    expect(midiForCode("KeyZ", 10)).toBeNull(); // below A0
    expect(midiForCode("BracketRight", 100)).toBeNull(); // above C8
  });

  it("leaves shortcuts, repeats and form fields alone", () => {
    const e = { ctrlKey: false, metaKey: false, altKey: false, repeat: false, target: { tagName: "DIV" } };
    expect(shouldIgnoreKeyEvent(e)).toBe(false);
    expect(shouldIgnoreKeyEvent({ ...e, ctrlKey: true })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, metaKey: true })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, repeat: true })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, target: { tagName: "INPUT" } })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, target: { tagName: "SELECT" } })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, target: { tagName: "DIV", isContentEditable: true } })).toBe(true);
    expect(shouldIgnoreKeyEvent({ ...e, target: null })).toBe(false);
  });
});

describe("Space and the sustain pedal", () => {
  const el = (matches: boolean) => ({ closest: () => (matches ? {} : null) });

  it("is left to buttons, links, tabs and piano keys, which use Space themselves", () => {
    expect(spaceBelongsToControl(el(true))).toBe(true);
  });

  it("is the pedal anywhere else, including with no focused element", () => {
    expect(spaceBelongsToControl(el(false))).toBe(false);
    expect(spaceBelongsToControl(null)).toBe(false);
    expect(spaceBelongsToControl(undefined)).toBe(false);
    expect(spaceBelongsToControl({})).toBe(false);
  });

  it("does not mistake a modifier shortcut for the pedal", () => {
    const base = { ctrlKey: false, metaKey: false, altKey: false, repeat: false, target: null };
    expect(shouldIgnoreKeyEvent({ ...base, ctrlKey: true })).toBe(true);
  });
});
