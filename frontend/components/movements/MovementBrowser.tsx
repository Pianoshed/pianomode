"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/Skeleton";
import { prettyNote, selectClass, useDebounced } from "@/components/piano/shared";
import { failureText } from "@/lib/api";
import { LEVELS, LEVEL_INFO, type ListFilters, type MovementSummary, listMovements } from "@/lib/movements/api";

export function MovementBrowser() {
  const [q, setQ] = useState("");
  const [level, setLevel] = useState<ListFilters["level"]>("");
  const [mode, setMode] = useState<ListFilters["mode"]>("");
  const dq = useDebounced(q, 250);
  const [items, setItems] = useState<MovementSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listMovements({ q: dq.trim(), level, mode }).then((r) => {
      if (cancelled) return;
      if (r.ok) {
        setItems(r.data.items);
        setError(null);
      } else setError(failureText(r));
    });
    return () => {
      cancelled = true;
    };
  }, [dq, level, mode]);

  const filtered = Boolean(dq.trim() || level || mode);

  return (
    <div className="space-y-5">
      <form role="search" className="grid gap-3 sm:grid-cols-3" onSubmit={(e) => e.preventDefault()}>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Search</span>
          <input
            type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="ii-V-I, gospel, blues…"
            maxLength={60} className={selectClass}
          />
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Level</span>
          <select className={selectClass} value={level} onChange={(e) => setLevel(e.target.value as ListFilters["level"])}>
            <option value="">Any level</option>
            {LEVELS.map((l) => <option key={l} value={l}>{LEVEL_INFO[l].label}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          <span className="mb-1.5 block font-medium">Key type</span>
          <select className={selectClass} value={mode} onChange={(e) => setMode(e.target.value as ListFilters["mode"])}>
            <option value="">Major and minor</option>
            <option value="major">Major</option>
            <option value="minor">Minor</option>
          </select>
        </label>
      </form>

      {error ? <Notice tone="error">{error}</Notice> : null}
      {items === null && !error ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40" />)}
        </div>
      ) : null}
      {items?.length === 0 ? (
        <EmptyState>
          {filtered
            ? "No movement matches those filters. Try fewer filters or a different word."
            : "No movements are published yet. An educator can publish them from Content Admin."}
        </EmptyState>
      ) : null}
      <p className="sr-only" role="status">{items ? `${items.length} movements` : ""}</p>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {items?.map((m) => (
          <li key={m.slug}>
            <Link
              href={`/progressions/${m.slug}`}
              className="flex h-full flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span className="text-lg font-bold">{prettyNote(m.name)}</span>
              <span className="text-sm text-muted">{prettyNote(m.key)} · {m.tempo} BPM · {m.time_signature.join("/")}</span>
              <span className="text-sm">{m.chords.slice(0, 8).map(prettyNote).join("  ")}{m.chords.length > 8 ? " …" : ""}</span>
              <span className="mt-auto flex flex-wrap gap-1.5 pt-1">
                {m.tags.slice(0, 4).map((t) => (
                  <span key={t} className="rounded-full bg-surface-2 px-2.5 py-0.5 text-xs text-muted">{t}</span>
                ))}
              </span>
              <span className="text-xs text-muted">{m.levels.length} levels, beginner to expert</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
