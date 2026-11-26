"use client";

import { useCallback, useEffect, useState } from "react";
import { ExamplePlayer } from "@/components/lessons/ExamplePlayer";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { failureText } from "@/lib/api";
import {
  type AdminLesson,
  type AdminLessonSummary,
  type AdminStatus,
  EXAMPLE_FIELDS,
  type ExampleForm,
  LEVEL_OPTIONS,
  type LessonForm,
  type LessonPreview,
  createLesson,
  definitionFromForm,
  emptyExample,
  emptyForm,
  formFromDefinition,
  getAdminLesson,
  lessonTransitionLabel,
  listAdminLessons,
  previewLessonDraft,
  previewStoredLesson,
  setLessonStatus,
  updateLesson,
} from "@/lib/lessons/admin";
import type { ExampleType } from "@/lib/lessons/api";
import { type ExerciseKind, listKinds } from "@/lib/theory/exercisesApi";

const STATUS_LABEL: Record<AdminStatus, string> = {
  draft: "Draft", under_review: "In review", approved: "Approved", published: "Published", archived: "Archived",
};
const field = "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";
const area = `${field} min-h-24 py-2`;
const EXAMPLE_TYPES: ExampleType[] = ["chord", "scale", "interval", "sequence"];

function Label({ text, children, hint }: { text: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1.5 block font-medium">{text}</span>
      {children}
      {hint ? <span className="mt-1 block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

/** Educators and admins write lessons as text plus example specifications. The engine builds the
 *  notes, so the preview here is exactly what learners will see and hear. */
export function LessonAdmin() {
  const [rows, setRows] = useState<AdminLessonSummary[] | null>(null);
  const [selected, setSelected] = useState<AdminLesson | null>(null);
  const [form, setForm] = useState<LessonForm | null>(null);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<LessonPreview | null>(null);
  const [kinds, setKinds] = useState<ExerciseKind[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  const reload = useCallback(async () => {
    const r = await listAdminLessons();
    if (r.ok) setRows(r.data.items);
    else setMessage({ tone: "error", text: failureText(r) });
  }, []);
  useEffect(() => {
    void reload();
    void listKinds().then((r) => r.ok && setKinds(r.data.kinds));
  }, [reload]);

  const open = async (id: string) => {
    const r = await getAdminLesson(id);
    if (!r.ok) return setMessage({ tone: "error", text: failureText(r) });
    setSelected(r.data); setForm(null); setPreview(null); setMessage(null);
  };

  const runPreview = async () => {
    if (!form) return;
    setBusy(true);
    const r = await previewLessonDraft(definitionFromForm(form));
    setBusy(false);
    if (r.ok) { setPreview(r.data); setMessage(null); }
    else { setPreview(null); setMessage({ tone: "error", text: failureText(r) }); }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    const def = definitionFromForm(form);
    const r = editing && selected ? await updateLesson(selected.id, { ...def, revision: selected.revision }) : await createLesson(def);
    setBusy(false);
    if (!r.ok) return setMessage({ tone: "error", text: failureText(r) });
    setSelected(r.data); setForm(null); setPreview(null);
    setMessage({ tone: "success", text: "Saved as a draft. Submit it for review when it is ready." });
    void reload();
  };

  const move = async (to: AdminStatus) => {
    if (!selected) return;
    setBusy(true);
    const r = await setLessonStatus(selected.id, to);
    setBusy(false);
    if (!r.ok) {
      const blockers = (r as { details?: { blockers?: string[] } }).details?.blockers;
      return setMessage({ tone: "error", text: failureText(r) + (blockers ? ` ${blockers.join(" ")}` : "") });
    }
    setSelected(r.data);
    setMessage({ tone: "success", text: `${lessonTransitionLabel(selected.status, to)} done.` });
    void reload();
  };

  const showStoredPreview = async () => {
    if (!selected) return;
    setBusy(true);
    const r = await previewStoredLesson(selected.id);
    setBusy(false);
    if (r.ok) setPreview(r.data);
    else setMessage({ tone: "error", text: failureText(r) });
  };

  const set = <K extends keyof LessonForm>(k: K, v: LessonForm[K]) => setForm((f) => (f ? { ...f, [k]: v } : f));
  const setSection = (i: number, patch: Partial<LessonForm["sections"][number]>) =>
    setForm((f) => f && { ...f, sections: f.sections.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const setExample = (i: number, k: number, patch: Partial<ExampleForm>) =>
    setForm((f) => f && { ...f, sections: f.sections.map((s, j) => (j === i ? { ...s, examples: s.examples.map((e, m) => (m === k ? { ...e, ...patch } : e)) } : s)) });

  const canEdit = selected?.status === "draft";

  return (
    <section aria-label="Lessons" className="space-y-4">
      <div>
        <h2 className="text-lg font-bold">Lessons</h2>
        <p className="text-sm text-muted">
          Write lessons as text plus example specifications. The theory engine builds every note, so lessons cannot disagree with the exercises. Built-in lessons are read only.
        </p>
      </div>
      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-3">
          <button type="button" className={buttonStyles()} onClick={() => { setSelected(null); setForm(emptyForm()); setEditing(false); setPreview(null); setMessage(null); }}>
            New lesson
          </button>
          <div className="rounded-xl border border-line bg-surface p-2">
            {rows?.length === 0 ? <p className="p-3 text-sm text-muted">No written lessons yet.</p> : null}
            <ul>
              {rows?.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => void open(r.id)} aria-current={selected?.id === r.id}
                    className={`flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2 ${selected?.id === r.id ? "bg-accent-soft" : ""}`}>
                    <span className="font-medium">{r.title}</span>
                    <span className="text-xs text-muted">{STATUS_LABEL[r.status]} · {r.level} · r{r.revision}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="space-y-4">
          {form ? (
            <form onSubmit={save} className="space-y-5 rounded-xl border border-line bg-surface p-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <Label text="Title"><input className={field} value={form.title} onChange={(e) => set("title", e.target.value)} required maxLength={120} /></Label>
                <Label text="Id (lower case, digits, hyphens)">
                  <input className={field} value={form.id} onChange={(e) => set("id", e.target.value)} required pattern="[a-z0-9][a-z0-9-]+" maxLength={64} disabled={editing && !canEdit} />
                </Label>
                <Label text="Level">
                  <select className={field} value={form.level} onChange={(e) => set("level", e.target.value as LessonForm["level"])}>
                    {LEVEL_OPTIONS.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </Label>
                <Label text="Prerequisite lesson ids" hint="Space separated. Each must already be live.">
                  <input className={field} value={form.prerequisites} onChange={(e) => set("prerequisites", e.target.value)} />
                </Label>
              </div>
              <Label text="Summary (one or two sentences)"><textarea className={area} value={form.summary} onChange={(e) => set("summary", e.target.value)} required maxLength={300} /></Label>
              <Label text="Learning objectives" hint="One per line, one to six."><textarea className={area} value={form.objectives} onChange={(e) => set("objectives", e.target.value)} required /></Label>

              <fieldset className="space-y-4">
                <legend className="text-sm font-semibold">Sections</legend>
                {form.sections.map((s, i) => (
                  <div key={i} className="space-y-3 rounded-lg border border-line p-4">
                    <Label text={`Section ${i + 1} heading`}><input className={field} value={s.heading} onChange={(e) => setSection(i, { heading: e.target.value })} required maxLength={120} /></Label>
                    <Label text="Text" hint="Separate paragraphs with a blank line."><textarea className={area} value={s.body} onChange={(e) => setSection(i, { body: e.target.value })} required /></Label>
                    {s.examples.map((ex, k) => (
                      <div key={k} className="space-y-3 rounded-lg bg-surface-2 p-3">
                        <div className="flex flex-wrap items-end gap-3">
                          <Label text="Example type">
                            <select className={`${field} w-40`} value={ex.type} onChange={(e) => setExample(i, k, { type: e.target.value as ExampleType, fields: {} })}>
                              {EXAMPLE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                            </select>
                          </Label>
                          <button type="button" className={buttonStyles({ variant: "secondary" })}
                            onClick={() => setSection(i, { examples: s.examples.filter((_, m) => m !== k) })}>Remove example</button>
                        </div>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {EXAMPLE_FIELDS[ex.type].map((fd) => (
                            <Label key={fd.key} text={fd.label}>
                              <input className={`${field} font-mono`} placeholder={fd.hint} value={ex.fields[fd.key] ?? ""}
                                onChange={(e) => setExample(i, k, { fields: { ...ex.fields, [fd.key]: e.target.value } })} />
                            </Label>
                          ))}
                        </div>
                        <Label text="Caption (what the learner should notice)"><input className={field} value={ex.caption} onChange={(e) => setExample(i, k, { caption: e.target.value })} required maxLength={200} /></Label>
                      </div>
                    ))}
                    <div className="flex flex-wrap gap-2">
                      <button type="button" className={buttonStyles({ variant: "secondary" })} disabled={s.examples.length >= 6}
                        onClick={() => setSection(i, { examples: [...s.examples, emptyExample()] })}>Add example</button>
                      {form.sections.length > 1 ? (
                        <button type="button" className={buttonStyles({ variant: "secondary" })}
                          onClick={() => setForm((f) => f && { ...f, sections: f.sections.filter((_, j) => j !== i) })}>Remove section</button>
                      ) : null}
                    </div>
                  </div>
                ))}
                <button type="button" className={buttonStyles({ variant: "secondary" })} disabled={form.sections.length >= 12}
                  onClick={() => setForm((f) => f && { ...f, sections: [...f.sections, { heading: "", body: "", examples: [] }] })}>Add section</button>
              </fieldset>

              <fieldset className="space-y-3">
                <legend className="text-sm font-semibold">Practice goals</legend>
                {form.practice.map((p, i) => (
                  <div key={i} className="grid gap-3 sm:grid-cols-[2fr_1fr_6rem_auto] sm:items-end">
                    <Label text="Exercise">
                      <select className={field} value={p.kind} required onChange={(e) => set("practice", form.practice.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
                        <option value="">Choose…</option>
                        {kinds.map((k) => <option key={k.kind} value={k.kind}>{k.title}</option>)}
                      </select>
                    </Label>
                    <Label text="Difficulty">
                      <select className={field} value={p.difficulty} onChange={(e) => set("practice", form.practice.map((x, j) => (j === i ? { ...x, difficulty: e.target.value as typeof p.difficulty } : x)))}>
                        {LEVEL_OPTIONS.map((l) => <option key={l} value={l}>{l}</option>)}
                      </select>
                    </Label>
                    <Label text="Goal">
                      <input className={field} inputMode="numeric" value={p.goal} onChange={(e) => set("practice", form.practice.map((x, j) => (j === i ? { ...x, goal: e.target.value } : x)))} />
                    </Label>
                    {form.practice.length > 1 ? (
                      <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => set("practice", form.practice.filter((_, j) => j !== i))}>Remove</button>
                    ) : null}
                  </div>
                ))}
                <button type="button" className={buttonStyles({ variant: "secondary" })} disabled={form.practice.length >= 6}
                  onClick={() => set("practice", [...form.practice, { kind: "", difficulty: form.level, goal: "3" }])}>Add practice goal</button>
              </fieldset>

              <div className="grid gap-4 sm:grid-cols-2">
                <Label text="Linked progression (optional)" hint="A progression template id, such as ii_v_i."><input className={`${field} font-mono`} value={form.movement_template} onChange={(e) => set("movement_template", e.target.value)} /></Label>
                <Label text="Tags" hint="Space separated."><input className={field} value={form.tags} onChange={(e) => set("tags", e.target.value)} /></Label>
              </div>

              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} onClick={() => void runPreview()} className={buttonStyles({ variant: "secondary" })}>Preview</button>
                <button type="submit" disabled={busy} className={buttonStyles()}>{editing ? "Save changes" : "Save draft"}</button>
                <button type="button" onClick={() => { setForm(null); setPreview(null); }} className={buttonStyles({ variant: "secondary" })}>Cancel</button>
              </div>
            </form>
          ) : null}

          {selected && !form ? (
            <div className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-label="Selected lesson">
              <div>
                <h3 className="text-lg font-bold">{selected.title}</h3>
                <p className="text-sm text-muted">{STATUS_LABEL[selected.status]} · revision {selected.revision} · {selected.level} · id {selected.lesson_id}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} className={buttonStyles({ variant: "secondary" })} onClick={() => void showStoredPreview()}>Preview and check</button>
                {canEdit || selected.status === "under_review" || selected.status === "approved" ? (
                  <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => { setForm(formFromDefinition(selected.definition)); setEditing(true); setPreview(null); }}>Edit</button>
                ) : null}
                {selected.allowed_transitions.map((to) => (
                  <button key={to} type="button" disabled={busy} className={buttonStyles({ variant: to === "published" ? "primary" : "secondary" })} onClick={() => void move(to as AdminStatus)}>
                    {lessonTransitionLabel(selected.status, to as AdminStatus)}
                  </button>
                ))}
              </div>
              {selected.status === "published" ? <p className="text-xs text-muted">To edit a published lesson, unpublish it first. Learners stop seeing it until it is published again.</p> : null}
              {selected.status === "under_review" || selected.status === "approved" ? <p className="text-xs text-muted">Editing sends the lesson back to draft so the change is reviewed.</p> : null}
              <div>
                <h4 className="mb-1.5 text-sm font-semibold">History</h4>
                <ol className="space-y-1 text-sm">
                  {[...selected.history].reverse().map((h, i) => (
                    <li key={`${h.at}-${i}`} className="flex flex-wrap gap-x-2">
                      <span className="font-medium">{h.action.replace(/_/g, " ")}</span>
                      <span className="text-muted">r{h.revision} · {h.actor} · {new Date(h.at).toLocaleString()}</span>
                      {h.note ? <span className="w-full text-muted">{h.note}</span> : null}
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          ) : null}

          {preview ? <PreviewPanel p={preview} /> : null}
          {!selected && !form ? <p className="text-sm text-muted">Choose a lesson, or write a new one.</p> : null}
        </div>
      </div>
    </section>
  );
}

function PreviewPanel({ p }: { p: LessonPreview }) {
  const l = p.lesson;
  return (
    <div className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-live="polite" data-testid="lesson-preview">
      <Notice tone={p.publishable ? "success" : "error"}>
        {p.publishable ? (p.can_publish_now ? "Ready to publish." : "Passes the publication checks. It must be approved before publishing.") : `Not ready to publish: ${p.blockers.join(" ")}`}
      </Notice>
      {p.warnings.length ? <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : null}
      <div>
        <h3 className="text-xl font-extrabold tracking-tight">{l.title}</h3>
        <p className="text-sm text-muted">{l.level} · {l.summary}</p>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm">{l.objectives.map((o) => <li key={o}>{o}</li>)}</ul>
      {l.sections.map((s) => (
        <section key={s.heading} className="space-y-3">
          <h4 className="font-semibold">{s.heading}</h4>
          {s.body.map((b, i) => <p key={i} className="text-sm">{b}</p>)}
          {s.examples.map((e, i) => <ExamplePlayer key={i} example={e} />)}
        </section>
      ))}
      <p className="text-xs text-muted">Practice: {l.practice.map((g) => `${g.title} (${g.difficulty}, ${g.goal})`).join("; ")}</p>
    </div>
  );
}
