"use client";

import { CheckCircle2, Circle, CircleDot, Volume2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { prettyNote } from "@/components/piano/shared";
import { PageHeader } from "@/components/PageHeader";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { type LessonDetail, type LessonStatus, getLesson } from "@/lib/lessons/api";
import { LEVEL_LABEL, STATUS_LABEL, goalText, practiceHref } from "@/lib/lessons/lesson";
import { ExamplePlayer } from "./ExamplePlayer";

export function StatusBadge({ status }: { status: LessonStatus }) {
  const Icon = status === "practised" ? CheckCircle2 : status === "in_progress" ? CircleDot : Circle;
  const tone = status === "practised" ? "text-accent" : "text-muted";
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${tone}`}>
      <Icon aria-hidden className="h-3.5 w-3.5" /> {STATUS_LABEL[status]}
    </span>
  );
}

export function LessonView({ id }: { id: string }) {
  const [lesson, setLesson] = useState<LessonDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLesson(null);
    setError(null);
    void getLesson(id).then((r) => {
      if (cancelled) return;
      if (r.ok) setLesson(r.data);
      else setError(failureText(r));
    });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (error) {
    return (
      <>
        <PageHeader title="Lesson" />
        <Notice tone="error">{error}</Notice>
        <Link href="/learn" className={`${buttonStyles({ variant: "ghost" })} mt-4`}>← All lessons</Link>
      </>
    );
  }
  if (!lesson) {
    return (
      <>
        <PageHeader title="Lesson" />
        <div className="space-y-4" aria-busy="true" aria-label="Loading lesson"><Skeleton className="h-32" /><Skeleton className="h-64" /></div>
      </>
    );
  }

  const unmet = lesson.prerequisites.filter((p) => p.status !== "practised");

  return (
    <>
    <PageHeader title={lesson.title} />
    <article className="max-w-3xl space-y-8">
      <header className="space-y-2">
        <p className="flex flex-wrap items-center gap-x-3 text-sm text-muted">
          <span>{LEVEL_LABEL[lesson.level]}</span>
          <StatusBadge status={lesson.status} />
        </p>
        <p className="text-base">{lesson.summary}</p>
      </header>

      {unmet.length ? (
        <Notice>
          This builds on{" "}
          {unmet.map((p, i) => (
            <span key={p.id}>
              {i > 0 ? (i === unmet.length - 1 ? " and " : ", ") : ""}
              <Link href={`/learn/${p.id}`} className="font-medium underline">{p.title}</Link>
            </span>
          ))}
          , which you have not finished practising. You can still read on.
        </Notice>
      ) : null}

      <section aria-labelledby="objectives" className="rounded-xl border border-line bg-surface p-5">
        <h2 id="objectives" className="mb-2 text-base font-semibold">What you will learn</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {lesson.objectives.map((o) => <li key={o}>{o}</li>)}
        </ul>
      </section>

      {lesson.sections.map((s) => (
        <section key={s.heading} aria-labelledby={`h-${s.heading}`}>
          <h2 id={`h-${s.heading}`} className="mb-2 text-lg font-bold">{s.heading}</h2>
          {s.body.map((p) => <p key={p} className="mb-3 max-w-[66ch] leading-relaxed">{prettyNote(p)}</p>)}
          {s.examples.map((e) => <ExamplePlayer key={e.caption} example={e} />)}
        </section>
      ))}

      <section aria-labelledby="practice" className="rounded-xl border border-line bg-surface p-5">
        <h2 id="practice" className="mb-1 text-lg font-bold">Practise</h2>
        <p className="mb-3 text-sm text-muted">Answer different exercises correctly to meet each goal. Repeating one question does not count twice.</p>
        <ul className="space-y-2">
          {lesson.practice.map((g) => (
            <li key={`${g.kind}-${g.difficulty}`} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-3 py-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                {g.met ? <CheckCircle2 aria-label="Goal met" className="h-4 w-4 text-accent" /> : <Circle aria-hidden className="h-4 w-4 text-muted" />}
                {g.title}
                {g.ear_training ? <Volume2 aria-label="Ear training" className="h-3.5 w-3.5 text-muted" /> : null}
              </span>
              <span className="flex items-center gap-3">
                <span className="text-sm text-muted">{goalText(g)} correct</span>
                <Link href={practiceHref(g)} className={buttonStyles({ variant: g.met ? "secondary" : "primary" })}>
                  {g.met ? "Practise more" : "Practise"}
                </Link>
              </span>
            </li>
          ))}
        </ul>
        {lesson.movement_slug ? (
          <p className="mt-4 text-sm">
            Hear it with both hands on the{" "}
            <Link href={`/progressions/${lesson.movement_slug}`} className="font-medium underline">chord progression page</Link>.
          </p>
        ) : null}
      </section>

      {lesson.next.length ? (
        <nav aria-label="Next lessons">
          <h2 className="mb-2 text-base font-semibold">What comes next</h2>
          <ul className="flex flex-wrap gap-2">
            {lesson.next.map((n) => (
              <li key={n.id}>
                <Link href={`/learn/${n.id}`} className={buttonStyles({ variant: "secondary" })}>{n.title}</Link>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
      <Link href="/learn" className={buttonStyles({ variant: "ghost" })}>← All lessons</Link>
    </article>
    </>
  );
}
