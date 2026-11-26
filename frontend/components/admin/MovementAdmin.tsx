"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { type ApiResult, api, failureText } from "@/lib/api";
import {
  type AdminMovement,
  type AdminSummary,
  type Status,
  type ValidationReport,
  adminCreate,
  adminGet,
  adminList,
  adminSetStatus,
  adminUpdate,
  adminValidate,
  transitionLabel,
} from "@/lib/movements/api";

type Template = { id: string; name: string; mode: "major" | "minor"; difficulty: string };
const STATUS_LABEL: Record<Status, string> = {
  draft: "Draft", under_review: "In review", approved: "Approved", published: "Published", archived: "Archived",
};
const TONICS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const field = "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";

type FormState = {
  name: string; template_id: string; tonic: string; tags: string; theory_explanation: string;
  tempo: number; author: string; source: string;
};
const EMPTY: FormState = { name: "", template_id: "", tonic: "C", tags: "", theory_explanation: "", tempo: 80, author: "", source: "" };

function fromDefinition(d: Record<string, unknown>): FormState {
  const key = (d.key ?? {}) as { tonic?: string };
  return {
    name: String(d.name ?? ""), template_id: String(d.template_id ?? ""), tonic: key.tonic ?? "C",
    tags: ((d.tags as string[] | undefined) ?? []).join(", "),
    theory_explanation: String(d.theory_explanation ?? ""), tempo: Number(d.tempo ?? 80),
    author: String(d.author ?? ""), source: String(d.source ?? ""),
  };
}

function MovementForm({
  templates, initial, movementId, revision, onSaved, onCancel,
}: {
  templates: Template[]; initial: FormState; movementId: string | null; revision: number | null;
  onSaved: (m: AdminMovement) => void; onCancel: () => void;
}) {
  const [f, setF] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tpl = templates.find((t) => t.id === f.template_id);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tpl) return setError("Choose a chord pattern.");
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      name: f.name.trim(), key: { tonic: f.tonic, mode: tpl.mode }, template_id: tpl.id, tempo: f.tempo,
      tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean),
      theory_explanation: f.theory_explanation,
      ...(f.author.trim() ? { author: f.author.trim() } : {}), ...(f.source.trim() ? { source: f.source.trim() } : {}),
    };
    const r = movementId === null || revision === null
        ? await adminCreate(body)
        : await adminUpdate(movementId, { ...body, revision });
    setBusy(false);
    if (r.ok) onSaved(r.data);
    else setError(r.code === "revision_conflict" ? "Someone else changed this movement. Close this form, reload it and apply your edit again." : failureText(r));
  };

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-label={revision === null ? "New movement" : "Edit movement"}>
      <h2 className="text-base font-semibold">{revision === null ? "New movement" : "Edit movement"}</h2>
      {error ? <Notice tone="error">{error}</Notice> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Name</span>
          <input required maxLength={120} className={field} value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Chord pattern</span>
          <select required className={selectClass} value={f.template_id} onChange={(e) => set("template_id", e.target.value)}>
            <option value="">Choose…</option>
            {templates.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.mode})</option>)}
          </select></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Key</span>
          <select className={selectClass} value={f.tonic} onChange={(e) => set("tonic", e.target.value)}>
            {TONICS.map((t) => <option key={t} value={t}>{t}{tpl ? ` ${tpl.mode}` : ""}</option>)}
          </select></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Tempo (BPM)</span>
          <input type="number" min={20} max={300} className={field} value={f.tempo} onChange={(e) => set("tempo", Number(e.target.value))} /></label>
        <label className="block text-sm sm:col-span-2"><span className="mb-1.5 block font-medium">Tags</span>
          <input className={field} value={f.tags} onChange={(e) => set("tags", e.target.value)} placeholder="jazz, turnaround" />
          <span className="mt-1 block text-xs text-muted">Separate with commas. At least one is needed to publish.</span></label>
        <label className="block text-sm sm:col-span-2"><span className="mb-1.5 block font-medium">Why it works</span>
          <textarea rows={4} maxLength={4000} className={`${field} py-2`} value={f.theory_explanation} onChange={(e) => set("theory_explanation", e.target.value)} /></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Author</span>
          <input maxLength={100} className={field} value={f.author} onChange={(e) => set("author", e.target.value)} placeholder="Defaults to you" /></label>
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Source</span>
          <input maxLength={200} className={field} value={f.source} onChange={(e) => set("source", e.target.value)} /></label>
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={busy} className={buttonStyles()}>{busy ? "Saving…" : "Save"}</button>
        <button type="button" onClick={onCancel} className={buttonStyles({ variant: "secondary" })}>Cancel</button>
      </div>
    </form>
  );
}

export function MovementAdmin() {
  const [status, setStatus] = useState<Status | "">("");
  const [rows, setRows] = useState<AdminSummary[] | null>(null);
  const [selected, setSelected] = useState<AdminMovement | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [form, setForm] = useState<"new" | "edit" | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    const r = await adminList(status);
    if (r.ok) setRows(r.data.items);
    else setMessage({ tone: "error", text: failureText(r) });
  }, [status]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    void api<{ templates: Template[] }>("/api/v1/theory/progressions/templates").then((r) => r.ok && setTemplates(r.data.templates));
  }, []);

  const open = async (id: string) => {
    setForm(null); setReport(null); setMessage(null);
    const r = await adminGet(id);
    if (r.ok) { setSelected(r.data); } else setMessage({ tone: "error", text: failureText(r) });
  };

  const act = async (fn: () => Promise<ApiResult<AdminMovement>>, done: string) => {
    setBusy(true); setMessage(null);
    const r = await fn();
    setBusy(false);
    if (r.ok) {
      setSelected(r.data); setReport(null);
      setMessage({ tone: "success", text: done });
      void reload();
    } else {
      const blockers = (r as { code: string }).code === "publication_blocked" ? " Run “Check” to see what is missing." : "";
      setMessage({ tone: "error", text: failureText(r) + blockers });
    }
  };

  const check = async () => {
    if (!selected) return;
    setBusy(true);
    const r = await adminValidate(selected.id);
    setBusy(false);
    if (r.ok) setReport(r.data); else setMessage({ tone: "error", text: failureText(r) });
  };

  const canEdit = selected && (selected.status === "draft" || selected.status === "under_review" || selected.status === "approved");

  return (
    <div className="space-y-6">
      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm"><span className="mb-1.5 block font-medium">Show</span>
          <select className={`${selectClass} w-48`} value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">All statuses</option>
            {(Object.keys(STATUS_LABEL) as Status[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select></label>
        <button type="button" className={buttonStyles()} onClick={() => { setSelected(null); setForm("new"); setMessage(null); }}>New movement</button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-label="Movements" className="rounded-xl border border-line bg-surface p-2">
          {rows?.length === 0 ? <p className="p-3 text-sm text-muted">Nothing here yet.</p> : null}
          <ul>
            {rows?.map((r) => (
              <li key={r.id}>
                <button type="button" onClick={() => void open(r.id)} aria-current={selected?.id === r.id}
                  className={`flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2 ${selected?.id === r.id ? "bg-accent-soft" : ""}`}>
                  <span className="font-medium">{r.name}</span>
                  <span className="text-xs text-muted">{STATUS_LABEL[r.status]} · r{r.revision}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <div className="space-y-4">
          {form ? (
            <MovementForm
              templates={templates}
              initial={form === "edit" && selected ? fromDefinition(selected.definition) : EMPTY}
              movementId={form === "edit" && selected ? selected.id : null}
              revision={form === "edit" && selected ? selected.revision : null}
              onCancel={() => setForm(null)}
              onSaved={(m) => { setForm(null); setSelected(m); setMessage({ tone: "success", text: "Saved." }); void reload(); }}
            />
          ) : null}

          {selected && !form ? (
            <section className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-label="Selected movement">
              <div>
                <h2 className="text-lg font-bold">{selected.name}</h2>
                <p className="text-sm text-muted">{STATUS_LABEL[selected.status]} · revision {selected.revision} · {selected.mode}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link href={`/admin/preview/${selected.id}`} className={buttonStyles({ variant: "secondary" })}>Preview</Link>
                <button type="button" disabled={busy} onClick={() => void check()} className={buttonStyles({ variant: "secondary" })}>Check</button>
                {canEdit && selected.definition.template_id ? (
                  <button type="button" onClick={() => setForm("edit")} className={buttonStyles({ variant: "secondary" })}>Edit</button>
                ) : null}
                {selected.allowed_transitions.map((to) => (
                  <button key={to} type="button" disabled={busy} className={buttonStyles({ variant: to === "published" ? "primary" : "secondary" })}
                    onClick={() => void act(() => adminSetStatus(selected.id, to), `${transitionLabel(selected.status, to)} done.`)}>
                    {transitionLabel(selected.status, to)}
                  </button>
                ))}
              </div>
              {selected.status === "published" ? <p className="text-xs text-muted">To edit a published movement, unpublish it first. Learners then stop seeing it until it is published again.</p> : null}
              {canEdit && !selected.definition.template_id ? <p className="text-xs text-muted">This movement uses custom chords, which can be edited through the API for now.</p> : null}

              {report ? (
                <div className="space-y-2" aria-live="polite">
                  <Notice tone={report.publishable ? "success" : "error"}>
                    {report.publishable
                      ? report.can_publish_now ? "Ready to publish." : "Passes the publication checks. It must be approved before publishing."
                      : "Not ready to publish yet:"}
                  </Notice>
                  {report.blockers.length ? <ul className="list-disc space-y-1 pl-5 text-sm">{report.blockers.map((b) => <li key={b}>{b}</li>)}</ul> : null}
                  {report.warnings.length ? (
                    <details className="text-sm text-muted"><summary className="cursor-pointer">{report.warnings.length} warnings (do not block publishing)</summary>
                      <ul className="list-disc space-y-1 pl-5">{report.warnings.map((w) => <li key={w}>{w}</li>)}</ul></details>
                  ) : null}
                </div>
              ) : null}

              <div>
                <h3 className="mb-1.5 text-sm font-semibold">History</h3>
                <ol className="space-y-1 text-sm">
                  {[...selected.history].reverse().map((h, i) => (
                    <li key={`${h.at}-${i}`} className="flex flex-wrap gap-x-2">
                      <span className="font-medium">{h.action.replace(/_/g, " ")}</span>
                      <span className="text-muted">r{h.revision} · {h.by} · {new Date(h.at).toLocaleString()}</span>
                      {h.note ? <span className="w-full text-muted">{h.note}</span> : null}
                    </li>
                  ))}
                </ol>
              </div>
            </section>
          ) : null}
          {!selected && !form ? <p className="text-sm text-muted">Choose a movement, or create a new one.</p> : null}
        </div>
      </div>
    </div>
  );
}
