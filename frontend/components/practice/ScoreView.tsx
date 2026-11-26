"use client";

import { useState } from "react";
import type { Score } from "@/lib/practice/api";

export type PassScore = { pass: number; tempo: number; score: Score | null; error: string | null };

const pct = (n: number) => `${Math.round(n * 100)}%`;
const signed = (n: number | null) => (n === null ? "none" : `${n > 0 ? "+" : ""}${n} ms`);
const TENDENCY: Record<Score["timing"]["tendency"], string> = {
  rushing: "Tends to play early",
  dragging: "Tends to play late",
  steady: "Timing is steady",
  not_enough_notes: "Too few notes to judge rushing or dragging",
};

/** What a scored practice looks like: one chip per finished pass, and the detail of one. It states
 *  what the figures rest on and what was not judged; it never turns them into a grade. */
export function ScoreView({ passes }: { passes: PassScore[] }) {
  const [open, setOpen] = useState(0);
  const sel = passes[Math.min(open, passes.length - 1)];
  if (!sel) return null;
  const s = sel.score;
  return (
    <section aria-label="Results" className="space-y-4 rounded-xl border border-line bg-surface p-5" data-testid="score-view">
      <h2 className="text-base font-semibold">Results</h2>
      {passes.length > 1 ? (
        <ul className="flex flex-wrap gap-2" aria-label="Passes">
          {passes.map((p, i) => (
            <li key={p.pass}>
              <button type="button" aria-pressed={i === open} onClick={() => setOpen(i)}
                className={`min-h-11 rounded-lg border px-3 text-sm ${i === open ? "border-accent bg-accent-soft" : "border-line"}`}>
                Pass {p.pass + 1}: {p.score ? pct(p.score.accuracy) : "not scored"}
                <span className="ml-1.5 text-xs text-muted">{p.tempo} BPM</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {sel.error ? <p className="text-sm text-danger">{sel.error}</p> : null}
      {s ? (
        <div className="space-y-4">
          <p className="text-2xl font-extrabold tracking-tight">
            {pct(s.accuracy)} <span className="text-sm font-normal text-muted">{s.hits} of {s.expected} notes within {s.window_ms} ms · {s.tempo_bpm} BPM</span>
          </p>
          <ul className="list-disc space-y-1 pl-5 text-sm">{s.feedback.map((f) => <li key={f}>{f}</li>)}</ul>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
            {([["On the beat", s.on_time], ["Early", s.early], ["Late", s.late], ["Missed", s.missed], ["Wrong note", s.near_miss], ["Extra notes", s.extra]] as const).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-2"><dt className="text-muted">{k}</dt><dd className="font-semibold">{v}</dd></div>
            ))}
          </dl>
          <p className="text-sm">
            <span className="font-medium">{TENDENCY[s.timing.tendency]}.</span>{" "}
            <span className="text-muted">Average error {signed(s.timing.mean_error_ms)}, typical spread {s.timing.spread_ms === null ? "none" : `${s.timing.spread_ms} ms`}, over {s.timing.hits} hit notes.</span>
          </p>
          {s.hands.length ? <p className="text-sm text-muted">{s.hands.map((h) => `${h.hand === "L" ? "Left" : "Right"} hand ${pct(h.accuracy)} (${h.hit} of ${h.expected})`).join(" · ")}</p> : null}
          <ul className="space-y-0.5 text-xs text-muted">{s.limits.map((l) => <li key={l}>{l}</li>)}</ul>
          {s.saved_id ? <p className="text-xs text-muted">Saved to your history.</p> : null}
        </div>
      ) : null}
    </section>
  );
}
