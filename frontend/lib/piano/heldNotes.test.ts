import { describe, expect, it } from "vitest";
import { EMPTY_HELD, heldNotes, isHeld, press, release, releaseAll } from "./heldNotes";

describe("held notes", () => {
  it("tracks notes low to high without mutating earlier states", () => {
    const a = press(EMPTY_HELD, 64, "pointer");
    const b = press(a, 60, "keyboard");
    expect(heldNotes(a)).toEqual([64]);
    expect(heldNotes(b)).toEqual([60, 64]);
    expect(heldNotes(EMPTY_HELD)).toEqual([]);
  });

  it("keeps a note down until every source has let go", () => {
    let h = press(EMPTY_HELD, 60, "pointer");
    h = press(h, 60, "keyboard");
    h = release(h, 60, "pointer");
    expect(isHeld(h, 60)).toBe(true);
    h = release(h, 60, "keyboard");
    expect(isHeld(h, 60)).toBe(false);
  });

  it("counts repeated presses from one source", () => {
    let h = press(press(EMPTY_HELD, 60, "midi"), 60, "midi");
    h = release(h, 60, "midi");
    expect(isHeld(h, 60)).toBe(true);
    expect(isHeld(release(h, 60, "midi"), 60)).toBe(false);
  });

  it("ignores releasing something that is not down, returning the same state", () => {
    const h = press(EMPTY_HELD, 60, "pointer");
    expect(release(h, 62, "pointer")).toBe(h);
    expect(release(h, 60, "midi")).toBe(h);
  });

  it("can release everything", () => {
    expect(heldNotes(releaseAll(press(press(EMPTY_HELD, 60, "pointer"), 64, "midi")))).toEqual([]);
  });
});
