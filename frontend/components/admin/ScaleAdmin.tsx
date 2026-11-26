"use client";

import { useCallback, useEffect, useState } from "react";
import { selectClass } from "@/components/piano/shared";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { type ApiResult, failureText } from "@/lib/api";
import {
  type AdminScale,
  type AdminScaleSummary,
  type ScalePreview,
  type ScaleStatus,
  createScale,
  definitionFromForm,
  getAdminScale,
  listAdminScales,
  previewScale,
  scaleTransitionLabel,
  setScaleStatus,
  updateScale,
} from "@/lib/scales/api";

const STATUS_LABEL: Record<ScaleStatus, string> = { draft: "Draft", published: "Published", archived: "Archived" };
const field = "min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent";

type Form = { id: string; name: string; family: string; formula: string; descending: string; aliases: string; description: string };
const EMPTY: Form = { id: "", name: "", family: "custom", formula: "P1 M2 M3 P5 M6", descending: "", aliases: "", description: "" };

function toForm(s: AdminScale): Form {
  const d = s.definition;
  return {
    id: d.id ?? s.scale_id, name: d.name ?? s.name, family: d.family ?? "custom",
    formula: (d.formula ?? []).join(" "), descending: (d.descending ?? []).join(" "),
    aliases: (d.aliases ?? []).join(", "), description: d.description ?? "",
  };
}

/** Administrators define scales as interval formulas. The engine validates them on the server and
 *  shows how each one is spelled on all twelve roots before anything is published. */
export function ScaleAdmin() {
  const [rows, setRows] = useState<AdminScaleSummary[] | null>(null);
  const [selected, setSelected] = useState<AdminScale | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<ScalePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  const reload = useCallback(async () => {
    const r = await listAdminScales();
    if (r.ok) setRows(r.data.items);
    else setMessage({ tone: "error", text: failureText(r) });
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);

  const open = async (id: string) => {
    const r = await getAdminScale(id);
    if (!r.ok) return setMessage({ tone: "error", text: failureText(r) });
    setSelected(r.data); setForm(null); setPreview(null); setMessage(null);
  };

  const blockerText = (r: Extract<ApiResult<unknown>, { ok: false }>) => failureText(r);

  const runPreview = async () => {
    if (!form) return;
    setBusy(true);
    const r = await previewScale(definitionFromForm(form));
    setBusy(false);
    if (r.ok) { setPreview(r.data); setMessage(null); }
    else { setPreview(null); setMessage({ tone: "error", text: blockerText(r) }); }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    const def = definitionFromForm(form);
    const r = editing && selected ? await updateScale(selected.id, { ...def, revision: selected.revision }) : await createScale(def);
    setBusy(false);
    if (!r.ok) return setMessage({ tone: "error", text: blockerText(r) });
    setSelected(r.data); setForm(null); setPreview(null);
    setMessage({ tone: "success", text: "Saved as a draft. Publish it to make it available to learners." });
    void reload();
  };

  const move = async (to: ScaleStatus) => {
    if (!selected) return;
    setBusy(true);
    const r = await setScaleStatus(selected.id, to);
    setBusy(false);
    if (!r.ok) return setMessage({ tone: "error", text: blockerText(r) });
    setSelected(r.data);
    setMessage({ tone: "success", text: `${scaleTransitionLabel(selected.status, to)} done.` });
    void reload();
  };

  const set = (k: keyof Form, v: string) => setForm((f) => (f ? { ...f, [k]: v } : f));

  return (
    <section aria-label="Scale definitions" className="space-y-4">
      <div>
        <h2 className="text-lg font-bold">Scale definitions</h2>
        <p className="text-sm text-muted">
          Add scales as interval formulas. Published scales appear in the scale list and generator. Built-in scales cannot be changed.
        </p>
      </div>
      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-3">
          <button type="button" className={buttonStyles()} onClick={() => { setSelected(null); setForm(EMPTY); setEditing(false); setPreview(null); setMessage(null); }}>
            New scale
          </button>
          <div className="rounded-xl border border-line bg-surface p-2">
            {rows?.length === 0 ? <p className="p-3 text-sm text-muted">No custom scales yet.</p> : null}
            <ul>
              {rows?.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => void open(r.id)} aria-current={selected?.id === r.id}
                    className={`flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2 ${selected?.id === r.id ? "bg-accent-soft" : ""}`}>
                    <span className="font-medium">{r.name}</span>
                    <span className="text-xs text-muted">{STATUS_LABEL[r.status]} · {r.size} notes · r{r.revision}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="space-y-4">
          {form ? (
            <form onSubmit={save} className="space-y-4 rounded-xl border border-line bg-surface p-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Name</span>
                  <input className={field} value={form.name} onChange={(e) => set("name", e.target.value)} required maxLength={60} /></label>
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Id (letters, digits, underscores)</span>
                  <input className={field} value={form.id} onChange={(e) => set("id", e.target.value)} required pattern="[a-z][a-z0-9_]+" maxLength={40} disabled={editing && selected?.status !== "draft"} /></label>
              </div>
              <label className="block text-sm"><span className="mb-1.5 block font-medium">Intervals above the root, starting with P1</span>
                <input className={`${field} font-mono`} value={form.formula} onChange={(e) => set("formula", e.target.value)} required aria-describedby="formula-help" />
                <span id="formula-help" className="mt-1 block text-xs text-muted">Example: P1 M2 m3 A4 P5 m6 M7. P perfect, M major, m minor, A augmented, d diminished.</span></label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Descending form (optional)</span>
                  <input className={`${field} font-mono`} value={form.descending} onChange={(e) => set("descending", e.target.value)} /></label>
                <label className="block text-sm"><span className="mb-1.5 block font-medium">Family</span>
                  <input className={field} value={form.family} onChange={(e) => set("family", e.target.value)} maxLength={32} /></label>
              </div>
              <label className="block text-sm"><span className="mb-1.5 block font-medium">Other names (comma separated)</span>
                <input className={field} value={form.aliases} onChange={(e) => set("aliases", e.target.value)} /></label>
              <label className="block text-sm"><span className="mb-1.5 block font-medium">Description</span>
                <textarea className={`${field} min-h-20 py-2`} value={form.description} onChange={(e) => set("description", e.target.value)} maxLength={1000} /></label>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy} onClick={() => void runPreview()} className={buttonStyles({ variant: "secondary" })}>Check spelling</button>
                <button type="submit" disabled={busy} className={buttonStyles()}>{editing ? "Save changes" : "Save draft"}</button>
                <button type="button" onClick={() => { setForm(null); setPreview(null); }} className={buttonStyles({ variant: "secondary" })}>Cancel</button>
              </div>
              {preview ? <PreviewPanel p={preview} /> : null}
            </form>
          ) : null}

          {selected && !form ? (
            <div className="space-y-4 rounded-xl border border-line bg-surface p-5" aria-label="Selected scale">
              <div>
                <h3 className="text-lg font-bold">{selected.name}</h3>
                <p className="text-sm text-muted">{STATUS_LABEL[selected.status]} · revision {selected.revision} · id {selected.scale_id}</p>
                <p className="mt-1 font-mono text-sm">{(selected.definition.formula ?? []).join(" ")}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {selected.status === "draft" ? (
                  <button type="button" className={buttonStyles({ variant: "secondary" })} onClick={() => { setForm(toForm(selected)); setEditing(true); setPreview(null); }}>Edit</button>
                ) : null}
                {selected.allowed_transitions.map((to) => (
                  <button key={to} type="button" disabled={busy} className={buttonStyles({ variant: to === "published" ? "primary" : "secondary" })} onClick={() => void move(to)}>
                    {scaleTransitionLabel(selected.status, to)}
                  </button>
                ))}
              </div>
              {selected.status === "published" ? <p className="text-xs text-muted">To edit a published scale, unpublish it first. It disappears from the scale list until it is published again.</p> : null}
              <div>
                <h4 className="mb-1.5 text-sm font-semibold">History</h4>
                <ol className="space-y-1 text-sm">
                  {[...selected.history].reverse().map((h, i) => (
                    <li key={`${h.at}-${i}`} className="flex flex-wrap gap-x-2">
                      <span className="font-medium">{h.action}</span>
                      <span className="text-muted">r{h.revision} · {h.actor} · {new Date(h.at).toLocaleString()}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          ) : null}
          {!selected && !form ? <p className="text-sm text-muted">Choose a scale, or create a new one.</p> : null}
        </div>
      </div>
    </section>
  );
}

function PreviewPanel({ p }: { p: ScalePreview }) {
  return (
    <div className="space-y-3" aria-live="polite" data-testid="scale-preview">
      <Notice tone={p.blockers.length ? "error" : "success"}>
        {p.blockers.length ? `Cannot be published yet: ${p.blockers.join(" ")}` : `${p.size} notes. Nothing blocks publishing.`}
      </Notice>
      {p.warnings.map((w) => <p key={w} className="text-sm text-muted">{w}</p>)}
      <ul className="grid gap-1 text-sm sm:grid-cols-2">
        {p.roots.map((r) => (
          <li key={r.root} className="flex gap-2">
            <span className="w-8 font-semibold">{r.root}</span>
            <span className={r.notes ? "font-mono" : "text-muted"}>{r.notes ? r.notes.join(" ") : "cannot be spelled"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
