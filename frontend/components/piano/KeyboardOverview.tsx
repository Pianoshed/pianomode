"use client";

import { type PointerEvent, type RefObject, useEffect, useState } from "react";
import { KEYS, WHITE_COUNT } from "@/lib/piano/keys";
import type { MarkMap } from "@/lib/piano/highlight";

/** A small map of all 88 keys. Click or drag to move the keyboard; touch screens use it to scroll
 *  because the keys themselves capture touches for playing. */
export function KeyboardOverview({
  scrollRef,
  keyWidth,
  marks,
  held,
}: {
  scrollRef: RefObject<HTMLDivElement | null>;
  keyWidth: number;
  marks: MarkMap | undefined;
  held: ReadonlySet<number>;
}) {
  const [view, setView] = useState({ left: 0, width: 1 });

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => {
      const total = WHITE_COUNT * keyWidth;
      setView({ left: el.scrollLeft / total, width: Math.min(1, el.clientWidth / total) });
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [scrollRef, keyWidth]);

  const go = (e: PointerEvent<HTMLDivElement>) => {
    const el = scrollRef.current;
    if (!el) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const fraction = (e.clientX - rect.left) / rect.width;
    el.scrollLeft = fraction * WHITE_COUNT * keyWidth - el.clientWidth / 2;
  };

  return (
    <div
      aria-hidden
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId);
        go(e);
      }}
      onPointerMove={(e) => {
        if (e.buttons || e.pointerType === "touch") go(e);
      }}
      style={{ touchAction: "none" }}
      className="relative mt-2 h-7 cursor-ew-resize overflow-hidden rounded-md border border-line bg-surface-2"
    >
      {KEYS.filter((k) => !k.black).map((k) => (
        <span key={k.midi} style={{ left: `${(k.x / WHITE_COUNT) * 100}%`, width: `${100 / WHITE_COUNT}%` }} className="absolute inset-y-0 border-r border-line/60" />
      ))}
      {[...(marks?.keys() ?? []), ...held].map((midi) => {
        const k = KEYS.find((x) => x.midi === midi);
        if (!k) return null;
        return (
          <span
            key={`m${midi}`}
            style={{ left: `${((k.x + k.width / 2) / WHITE_COUNT) * 100}%` }}
            className={`absolute bottom-1 h-1.5 w-1.5 -translate-x-1/2 rounded-full ${held.has(midi) ? "bg-fg" : "bg-accent"}`}
          />
        );
      })}
      <span
        style={{ left: `${view.left * 100}%`, width: `${view.width * 100}%` }}
        className="absolute inset-y-0 rounded-sm border-2 border-accent bg-accent/15"
      />
    </div>
  );
}
