"use client";

import { Check, Lightbulb, Volume2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PianoKeyboard } from "@/components/piano/PianoKeyboard";
import { prettyNote, selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/Skeleton";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import { PianoAudio } from "@/lib/piano/audio";
import { keyFor } from "@/lib/piano/keys";
import { DEFAULT_PREFS, type Prefs, loadPrefs } from "@/lib/piano/prefs";
import {
  type Difficulty,
  type Exercise,
  type ExerciseKind,
  type Grade,
  type KindProgress,
  getProgress,
  gradeExercise,
  listKinds,
  newExercise,
} from "@/lib/theory/exercisesApi";
import {
  type Draft,
  EMPTY_DRAFT,
  STATUS_TEXT,
  answerFor,
  describeProgress,
  groupByTopic,
  overlayForExercise,
  progressFor,
  toggleKey,
  topicLabel,
  untriedPrerequisites,
} from "@/lib/theory/practice";

const LEVEL_LABEL: Record<Difficulty, string> = { beginner: "Beginner", intermediate: "Intermediate", advanced: "Advanced", expert: "Expert" };
const input = "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";

export function TheoryPractice() {
  const [kinds, setKinds] = useState<ExerciseKind[] | null>(null);
  const [difficulties, setDifficulties] = useState<Difficulty[]>(["beginner", "intermediate", "advanced", "expert"]);
  const [progress, setProgress] = useState<KindProgress[]>([]);
  const [kind, setKind] = useState<string | null>(null);
  const [difficulty, setDifficulty] = useState<Difficulty>("beginner");
  const [exercise, setExercise] = useState<Exercise | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [grade, setGrade] = useState<Grade | null>(null);
  const [hintOpen, setHintOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState({ answered: 0, correct: 0 });
  const [prefs, setPrefs] = useState<Prefs>(DEFAULT_PREFS);
  const [audioProblem, setAudioProblem] = useState<string | null>(null);

  // A lesson can link here with ?kind=…&level=…; read once, on arrival.
  const params = useSearchParams();
  const wanted = useRef({ kind: params.get("kind"), level: params.get("level") });

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const resultRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<PianoAudio | null>(null);
  const audio = useCallback(() => (audioRef.current ??= new PianoAudio()), []);

  useEffect(() => setPrefs(loadPrefs(window.localStorage)), []);
  useEffect(() => () => audioRef.current?.allNotesOff(), []);
  useEffect(() => {
    void listKinds().then((r) => {
      if (r.ok) {
        setKinds(r.data.kinds);
        setDifficulties(r.data.difficulties);
        const { kind: wantedKind, level } = wanted.current;
        if (wantedKind && r.data.kinds.some((k) => k.kind === wantedKind)) {
          const start = r.data.difficulties.find((d) => d === level) ?? "beginner";
          setDifficulty(start);
          setKind(wantedKind);
          void load(wantedKind, start);
        }
      } else setError(failureText(r));
    });
    void getProgress().then((r) => r.ok && setProgress(r.data.items));
  }, []);

  const current = kinds?.find((k) => k.kind === kind) ?? null;
  const groups = useMemo(() => groupByTopic(kinds ?? []), [kinds]);

  const load = useCallback(async (k: string, d: Difficulty) => {
    setBusy(true);
    setError(null);
    setGrade(null);
    setDraft(EMPTY_DRAFT);
    setHintOpen(false);
    const r = await newExercise(k, d);
    setBusy(false);
    if (r.ok && r.data.exercises[0]) setExercise(r.data.exercises[0]);
    else if (!r.ok) setError(failureText(r));
  }, []);

  const choose = (k: string) => {
    setKind(k);
    void load(k, difficulty);
  };
  const changeDifficulty = (d: Difficulty) => {
    setDifficulty(d);
    if (kind) void load(kind, d);
  };

  // Keep the shown notes in view; with nothing highlighted, start around middle C so the learner
  // is not left looking at the lowest bass notes.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !exercise) return;
    const notes = exercise.show.length ? exercise.show : [60];
    const k = keyFor(Math.round((Math.min(...notes) + Math.max(...notes)) / 2));
    if (k) el.scrollLeft = Math.max(0, (k.x + 0.5) * prefs.keyWidth - el.clientWidth / 2);
  }, [exercise, prefs.keyWidth]);

  const play = useCallback(async () => {
    if (!exercise?.play.length) return;
    if (!(await audio().resume())) {
      setAudioProblem("This browser could not start sound.");
      return;
    }
    setAudioProblem(null);
    audio().allNotesOff();
    audio().schedule(exercise.play, exercise.tempo, prefs.layers);
  }, [audio, exercise, prefs.layers]);

  const submit = async () => {
    if (!exercise) return;
    const answer = answerFor(exercise.answer_format, draft);
    if (answer === null) return;
    setBusy(true);
    const r = await gradeExercise(exercise.id, answer);
    setBusy(false);
    if (!r.ok) {
      setError(failureText(r));
      return;
    }
    setError(null);
    setGrade(r.data);
    if (r.data.status !== "unreadable") {
      setSession((s) => ({ answered: s.answered + 1, correct: s.correct + (r.data.correct ? 1 : 0) }));
      void getProgress().then((p) => p.ok && setProgress(p.data.items));
    }
    requestAnimationFrame(() => resultRef.current?.focus());
  };

  const overlay = useMemo(() => overlayForExercise(exercise, draft.keys), [exercise, draft.keys]);
  const canPick = exercise?.answer_format === "note_set" && !grade;
  const answered = grade !== null && grade.status !== "unreadable";
  const ready = exercise ? answerFor(exercise.answer_format, draft) !== null : false;
  const missing = current && kinds ? untriedPrerequisites(current, kinds, progress) : [];
  const tone = grade ? STATUS_TEXT[grade.status] : null;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
      <nav aria-label="Exercise topics" className="space-y-4">
        {kinds === null && !error ? <Skeleton className="h-64" /> : null}
        {groups.map((g) => (
          <section key={g.topic}>
            <h2 className="mb-1.5 px-1 text-xs font-semibold uppercase tracking-wide text-muted">{topicLabel(g.topic)}</h2>
            <ul className="space-y-1">
              {g.kinds.map((k) => {
                const p = describeProgress(progressFor(progress, k.kind, difficulty));
                return (
                  <li key={k.kind}>
                    <button
                      type="button"
                      aria-current={kind === k.kind}
                      onClick={() => choose(k.kind)}
                      className={`flex min-h-11 w-full flex-col items-start rounded-lg border px-3 py-2 text-left text-sm ${kind === k.kind ? "border-accent bg-accent-soft" : "border-line bg-surface hover:bg-surface-2"}`}
                    >
                      <span className="flex w-full items-center justify-between gap-2 font-medium">
                        {k.title}
                        {k.ear_training ? <Volume2 aria-label="Ear training" className="h-3.5 w-3.5 text-muted" /> : null}
                      </span>
                      <span className="text-xs text-muted">{p.summary}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>

      <div className="min-w-0 space-y-5">
        {error ? <Notice tone="error">{error}</Notice> : null}
        {!exercise && !error ? (
          <Notice>Choose a topic on the left to get an exercise. Every question is generated and marked by the theory engine.</Notice>
        ) : null}

        {current ? (
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">{current.title}</h2>
              <p className="max-w-[60ch] text-sm text-muted">{current.objective}</p>
            </div>
            <label className="block text-sm">
              <span className="mb-1.5 block font-medium">Level</span>
              <select className={`${selectClass} w-44`} value={difficulty} onChange={(e) => changeDifficulty(e.target.value as Difficulty)}>
                {difficulties.map((d) => <option key={d} value={d}>{LEVEL_LABEL[d]}</option>)}
              </select>
            </label>
          </div>
        ) : null}
        {missing.length ? <Notice>This builds on {missing.join(" and ")}, which you have not tried yet. You can still start here.</Notice> : null}

        {exercise ? (
          <>
            <div className="rounded-xl border border-line bg-surface p-3">
              <PianoKeyboard
                keyWidth={prefs.keyWidth}
                held={draft.keys}
                overlay={overlay}
                labels={{ mode: "none", accidentals: prefs.accidentals, middleC: prefs.middleC, unicode: prefs.unicode }}
                scrollRef={scrollRef}
                onKeyDown={(n, v) => {
                  void audio().resume().then(() => audio().noteOn(n, v, prefs.layers));
                  if (canPick) setDraft((d) => ({ ...d, keys: toggleKey(d.keys, n) }));
                }}
                onKeyUp={(n) => audio().noteOff(n)}
              />
              {exercise.show.length ? <p className="mt-2 text-xs text-muted">Highlighted keys are part of the question.</p> : null}
              {canPick ? <p className="mt-2 text-xs text-muted">Press keys to build your answer (dark marks are your keys). Press a key again to remove it.</p> : null}
            </div>
            {audioProblem ? <Notice tone="error">{audioProblem}</Notice> : null}

            <form
              className="space-y-4 rounded-xl border border-line bg-surface p-5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!answered) void submit();
              }}
              aria-label="Exercise"
            >
              <p className="text-base font-semibold leading-snug">{prettyNote(exercise.prompt)}</p>

              {exercise.play.length ? (
                <button type="button" onClick={() => void play()} className={buttonStyles({ variant: "secondary" })}>
                  <Volume2 aria-hidden className="h-4 w-4" /> {current?.ear_training ? "Listen" : "Hear it"}
                </button>
              ) : null}

              {exercise.answer_format === "choice" ? (
                <fieldset disabled={answered}>
                  <legend className="sr-only">Choose one answer</legend>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {exercise.choices.map((c) => (
                      <label
                        key={c}
                        className={`flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg border px-3 text-sm ${draft.choice === c ? "border-accent bg-accent-soft" : "border-line hover:bg-surface-2"}`}
                      >
                        <input type="radio" name="choice" checked={draft.choice === c} onChange={() => setDraft((d) => ({ ...d, choice: c }))} className="accent-[rgb(var(--c-accent))]" />
                        {prettyNote(c)}
                      </label>
                    ))}
                  </div>
                </fieldset>
              ) : (
                <label className="block text-sm">
                  <span className="mb-1.5 block font-medium">Your answer</span>
                  <input
                    type="text" autoComplete="off" autoCapitalize="off" spellCheck={false} disabled={answered}
                    value={draft.text} onChange={(e) => setDraft((d) => ({ ...d, text: e.target.value }))}
                    aria-describedby="answer-help" className={input}
                  />
                  <span id="answer-help" className="mt-1 block text-xs text-muted">{exercise.answer_help}</span>
                </label>
              )}

              {exercise.hint ? (
                <div>
                  <button type="button" aria-expanded={hintOpen} onClick={() => setHintOpen((h) => !h)} className="inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-accent">
                    <Lightbulb aria-hidden className="h-4 w-4" /> {hintOpen ? "Hide hint" : "Show a hint"}
                  </button>
                  {hintOpen ? <p className="text-sm text-muted">{exercise.hint}</p> : null}
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2">
                {!answered ? (
                  <button type="submit" disabled={!ready || busy} className={buttonStyles()}>
                    <Check aria-hidden className="h-4 w-4" /> {busy ? "Checking…" : "Check answer"}
                  </button>
                ) : null}
                {answered ? (
                  <button type="button" onClick={() => kind && void load(kind, difficulty)} className={buttonStyles({ variant: "primary" })}>
                    Next exercise
                  </button>
                ) : null}
              </div>
            </form>

            {grade && tone ? (
              <div ref={resultRef} tabIndex={-1} aria-live="polite" className="space-y-3 outline-none">
                <Notice tone={tone.tone}>
                  <p className="font-semibold">{tone.title}</p>
                  <p className="mt-1">{prettyNote(grade.feedback)}</p>
                </Notice>
                {grade.status !== "unreadable" && !grade.correct ? (
                  <div className="rounded-xl border border-line bg-surface p-4 text-sm">
                    <p><span className="font-semibold">Answer: </span>{prettyNote(grade.correct_answer)}</p>
                    {grade.explanation ? <p className="mt-1 max-w-[64ch] text-muted">{prettyNote(grade.explanation)}</p> : null}
                  </div>
                ) : grade.explanation ? (
                  <p className="max-w-[64ch] text-sm text-muted">{prettyNote(grade.explanation)}</p>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}

        {session.answered > 0 ? (
          <p className="text-sm text-muted" role="status">This visit: {session.correct} of {session.answered} correct.</p>
        ) : null}
        <p className="text-xs text-muted">Questions and marking come from the platform&apos;s theory engine, not a language model. Counts record graded answers only.</p>
      </div>
    </div>
  );
}
