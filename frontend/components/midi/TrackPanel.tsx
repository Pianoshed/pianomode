"use client";

import { useState } from "react";
import { prettyNote } from "@/components/piano/shared";
import { buttonStyles } from "@/components/ui/button";
import type { TrackHandTag } from "@/lib/midi/api";
import { type TrackState, type TrackSummary, midiNoteName } from "@/lib/midi/studio";

const HAND_TAG: { value: TrackHandTag | ""; label: string }[] = [
  { value: "", label: "Not set" },
  { value: "L", label: "Left hand" },
  { value: "R", label: "Right hand" },
  { value: "both", label: "Both hands" },
  { value: "other", label: "Not a hand" },
];
const sel = "min-h-11 rounded-lg border border-line bg-surface px-2 text-sm";

export function TrackPanel({
  tracks,
  states,
  changeCount,
  canSplit,
  onState,
  onMerge,
  onSplit,
  onUndo,
  onReset,
}: {
  tracks: TrackSummary[];
  states: Readonly<Record<number, TrackState>>;
  changeCount: number;
  canSplit: boolean;
  onState: (track: number, patch: Partial<TrackState>) => void;
  onMerge: (from: number, into: number) => void;
  onSplit: (track: number, pitch: number) => void;
  onUndo: () => void;
  onReset: () => void;
}) {
  const [splitAt, setSplitAt] = useState<Record<number, number>>({});
  const soloing = tracks.some((t) => states[t.index]?.solo);
  return (
    <section aria-label="Tracks" className="space-y-3 rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">Tracks</h2>
        {changeCount > 0 ? (
          <span className="flex items-center gap-2 text-sm text-muted">
            {changeCount} track change{changeCount === 1 ? "" : "s"}
            <button type="button" onClick={onUndo} className={buttonStyles({ variant: "secondary" })}>Undo</button>
            <button type="button" onClick={onReset} className={buttonStyles({ variant: "ghost" })}>Reset</button>
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted">
        A track is not assumed to be a hand. Tell the Studio which hand a track is (or leave it unset) and it will use that for the notes in it; you can still change single notes in the roll.
      </p>
      <ul className="space-y-3">
        {tracks.map((t) => {
          const st = states[t.index] ?? { hand: null, muted: false, solo: false };
          const others = tracks.filter((o) => o.index !== t.index);
          const silent = st.muted || (soloing && !st.solo);
          return (
            <li key={t.index} className={`rounded-lg border border-line p-3 ${silent ? "opacity-60" : ""}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <span className="font-medium">{prettyNote(t.name)}</span>
                <span className="text-xs text-muted">
                  {t.noteCount} notes · {t.lowest !== null ? `${midiNoteName(t.lowest)} to ${midiNoteName(t.highest as number)}` : "no notes"}
                  {t.drumsOnly ? " · drums" : ""}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button type="button" aria-pressed={st.muted} onClick={() => onState(t.index, { muted: !st.muted })} className={`${buttonStyles({ variant: st.muted ? "primary" : "secondary" })}`}>
                  Mute
                </button>
                <button type="button" aria-pressed={st.solo} onClick={() => onState(t.index, { solo: !st.solo })} className={`${buttonStyles({ variant: st.solo ? "primary" : "secondary" })}`}>
                  Solo
                </button>
                <label className="flex items-center gap-1.5 text-sm">
                  <span className="text-muted">Hand</span>
                  <select className={sel} value={st.hand ?? ""} onChange={(e) => onState(t.index, { hand: (e.target.value || null) as TrackHandTag | null })} aria-label={`Hand for ${t.name}`}>
                    {HAND_TAG.map((h) => <option key={h.label} value={h.value}>{h.label}</option>)}
                  </select>
                </label>
                {others.length ? (
                  <label className="flex items-center gap-1.5 text-sm">
                    <span className="text-muted">Merge into</span>
                    <select className={sel} value="" aria-label={`Merge ${t.name} into another track`} onChange={(e) => e.target.value !== "" && onMerge(t.index, Number(e.target.value))}>
                      <option value="">Choose…</option>
                      {others.map((o) => <option key={o.index} value={o.index}>{o.name}</option>)}
                    </select>
                  </label>
                ) : null}
                {canSplit && t.lowest !== null && t.highest !== null && t.highest > t.lowest ? (
                  <span className="flex items-center gap-1.5 text-sm">
                    <label className="flex items-center gap-1.5">
                      <span className="text-muted">Split at</span>
                      <select className={sel} aria-label={`Split ${t.name} at pitch`} value={splitAt[t.index] ?? Math.round((t.lowest + t.highest) / 2)} onChange={(e) => setSplitAt((s) => ({ ...s, [t.index]: Number(e.target.value) }))}>
                        {Array.from({ length: t.highest - t.lowest }, (_, i) => t.lowest! + 1 + i).map((m) => <option key={m} value={m}>{midiNoteName(m)}</option>)}
                      </select>
                    </label>
                    <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => onSplit(t.index, splitAt[t.index] ?? Math.round((t.lowest! + t.highest!) / 2))}>
                      Split
                    </button>
                  </span>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
