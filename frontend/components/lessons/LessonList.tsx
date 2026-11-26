"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type LessonList as Data, listLessons } from "@/lib/lessons/api";
import { LEVEL_LABEL, groupByLevel, suggestNext, summaryCounts } from "@/lib/lessons/lesson";
import { StatusBadge } from "./LessonView";

export function LessonList() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void listLessons().then((r) => {
      if (cancelled) return;
      if (r.ok) setData(r.data);
      else setError(failureText(r));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) return <Notice tone="error">{error}</Notice>;
  if (!data) return <div className="space-y-4" aria-busy="true" aria-label="Loading lessons"><Skeleton className="h-24" /><Skeleton className="h-48" /></div>;

  const next = suggestNext(data.items);
  const { practised, total } = summaryCounts(data.items);
  const title = new Map(data.items.map((i) => [i.id, i.title]));

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface p-5">
        <p className="text-sm" role="status">
          <span className="text-lg font-bold">{practised} of {total}</span> lessons practised
        </p>
        {next ? (
          <Link href={`/learn/${next.id}`} className={buttonStyles({ variant: "primary" })}>
            {practised === 0 && next.status === "not_started" ? "Start with" : "Continue with"} {next.title}
          </Link>
        ) : (
          <p className="text-sm text-muted">Every lesson is practised. Revisit any of them below.</p>
        )}
      </div>

      {groupByLevel(data.items).map((g) => (
        <section key={g.level} aria-labelledby={`lv-${g.level}`}>
          <h2 id={`lv-${g.level}`} className="mb-3 text-lg font-bold">{LEVEL_LABEL[g.level]}</h2>
          <ul className="grid gap-4 sm:grid-cols-2">
            {g.lessons.map((l) => (
              <li key={l.id}>
                <Link
                  href={`/learn/${l.id}`}
                  className="flex h-full flex-col gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <span className="text-base font-bold">{l.title}</span>
                  <span className="text-sm text-muted">{l.summary}</span>
                  <span className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
                    <StatusBadge status={l.status} />
                    <span className="text-xs text-muted">{l.goals_met} of {l.goals_total} goals met</span>
                  </span>
                  {l.unmet_prerequisites.length ? (
                    <span className="text-xs text-muted">Builds on {l.unmet_prerequisites.map((p) => title.get(p) ?? p).join(", ")}</span>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
      <p className="text-xs text-muted">{data.note}</p>
    </div>
  );
}
