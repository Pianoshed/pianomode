"use client";

import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export const ROOTS: readonly { value: string; label: string }[] = [
  { value: "C", label: "C" },
  { value: "C#", label: "C♯" },
  { value: "Db", label: "D♭" },
  { value: "D", label: "D" },
  { value: "Eb", label: "E♭" },
  { value: "E", label: "E" },
  { value: "F", label: "F" },
  { value: "F#", label: "F♯" },
  { value: "Gb", label: "G♭" },
  { value: "G", label: "G" },
  { value: "Ab", label: "A♭" },
  { value: "A", label: "A" },
  { value: "Bb", label: "B♭" },
  { value: "B", label: "B" },
];

export const prettyNote = (name: string): string => name.replace(/##/g, "𝄪").replace(/#/g, "♯").replace(/(?<=[A-G])b/g, "♭");

export function RootPicker({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {ROOTS.map((r) => (
          <button
            key={r.value}
            type="button"
            aria-pressed={value === r.value}
            onClick={() => onChange(r.value)}
            className={`min-h-11 min-w-11 rounded-lg border px-2 text-sm font-semibold transition-colors ${
              value === r.value ? "border-accent bg-accent text-accent-fg" : "border-line bg-surface hover:bg-surface-2"
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

export const selectClass =
  "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";

export function Labelled({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) {
  return (
    <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--c-accent))]" />
      {children}
    </label>
  );
}
