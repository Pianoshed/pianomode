import { createRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PianoWorkspace } from "./PianoWorkspace";
import { PianoKeyboard } from "./PianoKeyboard";
import type { Overlay } from "@/lib/piano/highlight";

const labels = { mode: "c" as const, accidentals: "sharps" as const, middleC: 4, unicode: true };
const noop = () => undefined;

function render(overlay: Overlay | null = null, held: number[] = []) {
  return renderToStaticMarkup(
    <PianoKeyboard keyWidth={38} held={new Set(held)} overlay={overlay} labels={labels} scrollRef={createRef()} onKeyDown={noop} onKeyUp={noop} />,
  );
}

describe("PianoKeyboard (server render)", () => {
  it("renders all 88 keys with spoken names", () => {
    const html = render();
    expect(html.match(/data-midi="/g)).toHaveLength(88);
    expect(html).toContain('aria-label="A 0"');
    expect(html).toContain('aria-label="C sharp 4"');
    expect(html).toContain('aria-label="C 8"');
  });

  it("labels the C keys and gives exactly one key a tab stop", () => {
    const html = render();
    expect(html.match(/>C[1-8]</g)).toHaveLength(8); // C1 to C8; A0 is the lowest key
    expect(html.match(/tabindex="0"/g)).toHaveLength(1);
  });

  it("shows a mark's role, interval and bass in the key's name and draws the dot", () => {
    const overlay: Overlay = {
      source: "chord",
      title: "C",
      marks: new Map([
        [60, { role: "root", label: "R", bass: true }],
        [64, { role: "tone", label: "3" }],
      ]),
      spelling: {},
    };
    const html = render(overlay);
    expect(html).toContain('aria-label="C 4, root R, bass"');
    expect(html).toContain('aria-label="E 4, chord tone 3"');
    expect(html).toContain("rounded-md"); // the bass note is a square, not only a different colour
  });

  it("colours hands, and says which hand in the key's name", () => {
    const overlay: Overlay = {
      source: "chord",
      title: "C, both hands",
      marks: new Map([
        [48, { role: "root" as const, label: "R", hand: "L" as const, bass: true }],
        [64, { role: "tone" as const, label: "3", hand: "R" as const }],
      ]),
      spelling: {},
    };
    const html = render(overlay);
    expect(html).toContain("bg-hand-left");
    expect(html).toContain("bg-hand-right");
    expect(html).toContain("left hand");
    expect(html).toContain("right hand");
  });

  it("reports pressed keys to assistive technology", () => {
    const html = render(null, [60]);
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1);
    expect(html.match(/aria-pressed="false"/g)).toHaveLength(87);
  });

  it("uses the theory engine's spelling on the keys", () => {
    const overlay: Overlay = { source: "scale", title: "F# major", marks: new Map(), spelling: { 5: "E#" } };
    const html = renderToStaticMarkup(
      <PianoKeyboard keyWidth={38} held={new Set()} overlay={overlay} labels={{ ...labels, mode: "names" }} scrollRef={createRef()} onKeyDown={noop} onKeyUp={noop} />,
    );
    expect(html).toContain('aria-label="E sharp 4"'); // the F key is spelled E# in F# major
    expect(html).not.toContain('aria-label="F 4"');
  });
});

describe("PianoWorkspace (server render)", () => {
  it("renders without touching browser-only APIs, so Next can render it on the server", () => {
    const html = renderToStaticMarkup(<PianoWorkspace />);
    expect(html).toContain('role="tablist"');
    expect(html).toContain("What am I playing?");
    expect(html).toContain("Stop all sound");
    expect(html.match(/data-midi="/g)).toHaveLength(88);
  });
});
