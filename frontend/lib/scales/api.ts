/** Typed calls to the administrator-defined scales API (admin role only; the server enforces it).
 *  Interval formulas are validated by the music-theory engine on the server; the browser only
 *  splits what the person typed into tokens. */

import { type ApiResult, api } from "@/lib/api";

export type ScaleStatus = "draft" | "published" | "archived";
export type ScaleDefinition = {
  id: string;
  name: string;
  family: string;
  formula: string[];
  descending: string[] | null;
  aliases: string[];
  description: string;
};
export type AdminScale = {
  id: string;
  scale_id: string;
  name: string;
  status: ScaleStatus;
  revision: number;
  definition: Partial<ScaleDefinition>;
  history: { revision: number; at: string; actor: string; action: string; note: string; from_status: string | null; to_status: string | null }[];
  allowed_transitions: ScaleStatus[];
  published_at: string | null;
  updated_at: string;
};
export type AdminScaleSummary = { id: string; scale_id: string; name: string; status: ScaleStatus; revision: number; size: number; updated_at: string };
export type ScalePreview = {
  scale_id: string;
  name: string;
  size: number;
  semitones: number[];
  roots: { root: string; notes: string[] | null; problem: string | null }[];
  same_pattern_as: string[];
  blockers: string[];
  warnings: string[];
};

const ADMIN = "/api/v1/admin/scales";

export const listAdminScales = (status?: ScaleStatus): Promise<ApiResult<{ items: AdminScaleSummary[]; total: number }>> =>
  api(status ? `${ADMIN}?status=${status}` : ADMIN);
export const getAdminScale = (id: string): Promise<ApiResult<AdminScale>> => api(`${ADMIN}/${id}`);
export const createScale = (body: ScaleDefinition): Promise<ApiResult<AdminScale>> => api(ADMIN, { method: "POST", body });
export const updateScale = (id: string, body: ScaleDefinition & { revision: number }): Promise<ApiResult<AdminScale>> =>
  api(`${ADMIN}/${id}`, { method: "PUT", body });
export const previewScale = (body: ScaleDefinition): Promise<ApiResult<ScalePreview>> => api(`${ADMIN}/preview`, { method: "POST", body });
export const setScaleStatus = (id: string, to: ScaleStatus, note = ""): Promise<ApiResult<AdminScale>> =>
  api(`${ADMIN}/${id}/status`, { method: "POST", body: { to, note } });

/** "P1 M2, m3  P4" -> ["P1","M2","m3","P4"]. Commas, spaces and dashes separate intervals. */
export function splitTokens(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter(Boolean);
}

/** Aliases are typed as words; spaces and hyphens become underscores to match the API form. */
export function splitAliases(text: string): string[] {
  return text
    .split(/[,;\n]+/)
    .map((t) => t.trim().toLowerCase().replace(/[\s-]+/g, "_"))
    .filter(Boolean);
}

export function definitionFromForm(f: { id: string; name: string; family: string; formula: string; descending: string; aliases: string; description: string }): ScaleDefinition {
  const down = splitTokens(f.descending);
  return {
    id: f.id.trim(),
    name: f.name.trim(),
    family: f.family.trim() || "custom",
    formula: splitTokens(f.formula),
    descending: down.length ? down : null,
    aliases: splitAliases(f.aliases),
    description: f.description.trim(),
  };
}

export const SCALE_TRANSITION_LABEL: Record<string, string> = {
  "draft>published": "Publish",
  "published>draft": "Unpublish",
  "draft>archived": "Archive",
  "published>archived": "Archive",
  "archived>draft": "Restore",
};
export const scaleTransitionLabel = (from: ScaleStatus, to: ScaleStatus): string => SCALE_TRANSITION_LABEL[`${from}>${to}`] ?? to;
