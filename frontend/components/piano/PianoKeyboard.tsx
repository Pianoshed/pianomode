"use client";

import { type KeyboardEvent, type PointerEvent, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Mark, Overlay } from "@/lib/piano/highlight";
import {
  BLACK_HEIGHT,
  KEYS,
  LOWEST_MIDI,
  HIGHEST_MIDI,
  type LabelOptions,
  type PianoKey,
  WHITE_COUNT,
  accessibleName,
  midiFromPoint,
  noteLabel,
  velocityFromY,
} from "@/lib/piano/keys";

type Props = {
  keyWidth: number;
  held: ReadonlySet<number>;
  overlay: Overlay | null;
  labels: Omit<LabelOptions, "spelling">;
  scrollRef: RefObject<HTMLDivElement | null>;
  onKeyDown: (midi: number, velocity: number) => void;
  onKeyUp: (midi: number) => void;
};

const keyboardHeight = (keyWidth: number): number => Math.round(Math.min(260, Math.max(150, keyWidth * 4.9)));

function Dot({ mark, size, bass }: { mark: Mark; size: number; bass: boolean }) {
  // Shape carries meaning as well as colour: a rounded square is the bass note.
  const shape = bass ? "rounded-md" : "rounded-full";
  const tone: Record<Mark["role"], string> = {
    root: "bg-dot text-white border-key-white",
    tone: "bg-dot-soft text-dot border-dot",
    extra: "bg-key-white text-key-ink border-muted border-dashed",
    scale: "bg-dot-soft text-dot border-dot",
  };
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: size >= 18 ? 11 : 9 }}
      className={`flex items-center justify-center border-2 font-bold leading-none ${shape} ${tone[mark.role]}`}
    >
      {size >= 14 ? mark.label.slice(0, 3) : null}
    </span>
  );
}

export function PianoKeyboard({ keyWidth, held, overlay, labels, scrollRef, onKeyDown, onKeyUp }: Props) {
  const height = keyboardHeight(keyWidth);
  const surface = useRef<HTMLDivElement | null>(null);
  const pointers = useRef(new Map<number, number>()); // pointerId -> sounding midi
  const [focused, setFocused] = useState(60);
  const spelling = overlay?.spelling;
  const marks = overlay?.marks;

  const midiAt = useCallback(
    (e: PointerEvent): { midi: number; y: number } | null => {
      const el = surface.current;
      if (!el) return null;
      const rect = el.getBoundingClientRect();
      const x = (e.clientX - rect.left) / keyWidth;
      const y = (e.clientY - rect.top) / rect.height;
      const midi = midiFromPoint(x, y);
      return midi === null ? null : { midi, y };
    },
    [keyWidth],
  );

  const velocityAt = (midi: number, y: number): number => velocityFromY(y, KEYS.find((k) => k.midi === midi)?.black ?? false);

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    const hit = midiAt(e);
    if (!hit) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, hit.midi);
    setFocused(hit.midi);
    onKeyDown(hit.midi, velocityAt(hit.midi, hit.y));
  };

  const move = (e: PointerEvent<HTMLDivElement>) => {
    const current = pointers.current.get(e.pointerId);
    if (current === undefined) return;
    const hit = midiAt(e);
    if (!hit || hit.midi === current) return;
    // Sliding a finger or the mouse across keys plays each key in turn (a glissando).
    onKeyUp(current);
    pointers.current.set(e.pointerId, hit.midi);
    onKeyDown(hit.midi, velocityAt(hit.midi, hit.y));
  };

  const up = (e: PointerEvent<HTMLDivElement>) => {
    const current = pointers.current.get(e.pointerId);
    if (current === undefined) return;
    pointers.current.delete(e.pointerId);
    onKeyUp(current);
  };

  // If the component goes away mid-press, do not leave notes sounding.
  const upRef = useRef(onKeyUp);
  upRef.current = onKeyUp;
  useEffect(() => {
    const map = pointers.current;
    return () => {
      for (const midi of map.values()) upRef.current(midi);
      map.clear();
    };
  }, []);

  const keyDown = (e: KeyboardEvent<HTMLDivElement>, midi: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!e.repeat) onKeyDown(midi, 90);
      return;
    }
    const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    if (step === 0) return;
    e.preventDefault();
    const next = Math.min(HIGHEST_MIDI, Math.max(LOWEST_MIDI, midi + (e.shiftKey ? step * 12 : step)));
    setFocused(next);
    requestAnimationFrame(() => surface.current?.querySelector<HTMLElement>(`[data-midi="${next}"]`)?.focus({ preventScroll: false }));
  };
  const keyUp = (e: KeyboardEvent<HTMLDivElement>, midi: number) => {
    if (e.key === "Enter" || e.key === " ") onKeyUp(midi);
  };

  const rendered = useMemo(() => {
    const list = [...KEYS].sort((a, b) => Number(a.black) - Number(b.black)); // black keys draw on top
    return list;
  }, []);

  const renderKey = (k: PianoKey) => {
    const mark = marks?.get(k.midi);
    const pressed = held.has(k.midi);
    const label = noteLabel(k.midi, { ...labels, spelling });
    const w = k.width * keyWidth;
    const h = k.black ? height * BLACK_HEIGHT : height;
    const dotSize = k.black ? Math.max(10, Math.min(20, w - 4)) : Math.max(12, Math.min(24, w - 8));
    const base = k.black ? "bg-key-black text-key-ink-black rounded-b-md shadow-md" : "bg-key-white text-key-ink rounded-b-lg border-x border-b border-line";
    const name = accessibleName(k.midi, { accidentals: labels.accidentals, spelling, middleC: labels.middleC });
    const describe = mark ? `, ${mark.role === "root" ? "root" : mark.role === "extra" ? "extra note" : "chord tone"} ${mark.label}${mark.bass ? ", bass" : ""}${mark.hand ? (mark.hand === "L" ? ", left hand" : ", right hand") : ""}` : "";
    return (
      <div
        key={k.midi}
        data-midi={k.midi}
        role="button"
        tabIndex={focused === k.midi ? 0 : -1}
        aria-pressed={pressed}
        aria-label={`${name}${describe}`}
        onKeyDown={(e) => keyDown(e, k.midi)}
        onKeyUp={(e) => keyUp(e, k.midi)}
        onFocus={() => setFocused(k.midi)}
        style={{ left: k.x * keyWidth, width: w, height: h, zIndex: k.black ? 2 : 1, filter: pressed ? (k.black ? "brightness(2.2)" : "brightness(0.86)") : undefined, transform: pressed ? "translateY(1px)" : undefined }}
        className={`absolute top-0 select-none ${base} focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-accent`}
      >
        {mark?.hand ? <span aria-hidden className={`absolute inset-x-0 top-0 h-1.5 ${mark.hand === "L" ? "bg-hand-left" : "bg-hand-right"} ${k.black ? "rounded-t-none" : ""}`} /> : null}
        <div className="pointer-events-none absolute inset-x-0 bottom-1.5 flex flex-col items-center gap-1">
          {k.black && label ? <span className="text-[10px] font-semibold leading-none">{label}</span> : null}
          {mark ? <Dot mark={mark} size={dotSize} bass={mark.bass === true} /> : null}
          {!k.black && label ? <span className="text-[11px] font-semibold leading-none">{label}</span> : null}
        </div>
      </div>
    );
  };

  return (
    <div
      ref={scrollRef}
      className="overflow-x-auto overflow-y-hidden rounded-lg border border-line bg-key-black/90 pt-2.5 [scrollbar-width:thin]"
      role="group"
      aria-label="Piano keyboard, 88 keys from A0 to C8. Use the arrow keys to move between keys and Enter or Space to play."
    >
      <div
        ref={surface}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={up}
        onLostPointerCapture={up}
        onContextMenu={(e) => e.preventDefault()}
        style={{ width: WHITE_COUNT * keyWidth, height, touchAction: "none" }}
        className="relative"
      >
        {rendered.map(renderKey)}
      </div>
    </div>
  );
}
