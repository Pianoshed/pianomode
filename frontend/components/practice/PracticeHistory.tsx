"use client";

import { useCallback, useEffect, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type Attempt, type History, deleteAttempt, deleteHistory, getHistory } from "@/lib/practice/api";

const pct = (n: number) => `${Math.round(n * 100)}%`;
const when = (iso: string) => new Date(iso).toLocaleString();

/** The learner's own saved results and progress. Only they can see or delete them. */
export function PracticeHistory({ slug, refreshKey }: { slug?: string; refreshKey: number }) {
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);

  const load = useCallback(async () => {
    const r = await getHistory(slug);
    if (r.ok) { setData(r.data); setError(null); } else setError(failureText(r));
  }, [slug]);
  useEffect(() => { void load(); }, [load, refreshKey]);

  const remove = async (a: Attempt) => {
    const r = await deleteAttempt(a.id);
    if (r.ok) void load(); else setError(failureText(r));
  };
  const removeAll = async () => {
    const r = await deleteHistory();
    setConfirm(false);
    if (r.ok) void load(); else setError(failureText(r));
  };

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <p className="text-sm text-muted">Loading your history…</p>;
  if (data.total === 0) return <p className="text-sm text-muted">Nothing saved yet. Finish a pass in play mode, or a wait-mode run, and it appears here.</p>;

  return (
    <div className="space-y-6">
      <section aria-label="Progress" className="space-y-3">
        <h2 className="text-base font-semibold">Progress</h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {data.progress.map((p) => {
            const recent = data.items.filter((a) => a.movement_slug === p.movement_slug && a.level === p.level && a.mode === p.mode).slice(0, 12).reverse();
            return (
              <li key={`${p.movement_slug}|${p.level}|${p.mode}`} className="space-y-2 rounded-xl border border-line bg-surface p-4">
                <p className="font-medium">{p.movement_slug} <span className="text-sm font-normal text-muted">· {p.level} · {p.mode === "wait" ? "wait mode" : "play"}</span></p>
                <p className="text-sm text-muted">
                  {p.attempts} {p.attempts === 1 ? "result" : "results"} · best {pct(p.best_accuracy)} · latest {pct(p.last_accuracy)}
                  {p.best_tempo_at_90 ? ` · fastest tempo at 90% or better: ${p.best_tempo_at_90} BPM` : ""}
                </p>
                <div className="flex h-10 items-end gap-1" role="img" aria-label={`Accuracy of the last ${recent.length} results`}>
                  {recent.map((a) => <span key={a.id} className="w-3 rounded-sm bg-accent" style={{ height: `${Math.max(6, Math.round(a.accuracy * 100))}%` }} title={`${pct(a.accuracy)} · ${when(a.created_at)}`} />)}
                </div>
              </li>
            );
          })}
        </ul>
      </section>
      <section aria-label="Recent results" className="space-y-2">
        <h2 className="text-base font-semibold">Recent results</h2>
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {data.items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
              <span>
                <span className="font-medium">{pct(a.accuracy)}</span> {a.mode === "wait" ? `of ${a.expected} chords first time` : `${a.hits}/${a.expected} notes at ${a.tempo_bpm} BPM`}
                <span className="text-muted"> · {a.movement_slug} · {a.level}{a.hands !== "both" ? ` · ${a.hands === "L" ? "left" : "right"} hand` : ""} · {when(a.created_at)}</span>
              </span>
              <button type="button" onClick={() => void remove(a)} className={buttonStyles({ variant: "secondary" })} aria-label={`Delete the result from ${when(a.created_at)}`}>Delete</button>
            </li>
          ))}
        </ul>
        <p className="text-xs text-muted">Showing the latest {data.items.length} of {data.total}. Only results are kept, never the notes you played.</p>
      </section>
      <div>
        {confirm ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            Delete all {data.total} saved results?
            <button type="button" onClick={() => void removeAll()} className={buttonStyles({ variant: "primary" })}>Yes, delete all</button>
            <button type="button" onClick={() => setConfirm(false)} className={buttonStyles({ variant: "secondary" })}>Keep them</button>
          </span>
        ) : (
          <button type="button" onClick={() => setConfirm(true)} className={buttonStyles({ variant: "secondary" })}>Delete all my practice history</button>
        )}
      </div>
    </div>
  );
}
