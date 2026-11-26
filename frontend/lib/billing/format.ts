import type { BillingStatus, Credential, Entitlement } from "@/lib/billing/types";

/** 1500000 kobo -> "₦15,000". Shows kobo only when there are some. */
export function formatNaira(kobo: number): string {
  const naira = Math.floor(kobo / 100);
  const rest = kobo % 100;
  const whole = naira.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return rest === 0 ? `₦${whole}` : `₦${whole}.${rest.toString().padStart(2, "0")}`;
}

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "14 December 2026" in the viewer's own time zone. */
export function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export type StatusText = { headline: string; detail: string; tone: "info" | "success" | "error" };

/** Plain words for the person's current access. Used on the Subscription page and dashboard. */
export function describeEntitlement(e: Entitlement): StatusText {
  const until = e.ends_at ? formatDate(e.ends_at) : "";
  if (e.has_access) {
    switch (e.source) {
      case "staff":
        return { headline: "Staff access", detail: "Your role includes full access. No plan needed.", tone: "success" };
      case "trial":
        return {
          headline: `Free trial: ${plural(e.days_left ?? 0, "day")} left`,
          detail: `Your trial ends on ${until}. Choose a plan to carry on without a break.`,
          tone: "info",
        };
      case "institution":
        return {
          headline: `Access from ${e.institution_name ?? "your institution"}`,
          detail: `Your institution's plan runs until ${until}.`,
          tone: "success",
        };
      default:
        return {
          headline: "Individual plan",
          detail: `Paid until ${until} (${plural(e.days_left ?? 0, "day")} left). Plans do not renew by themselves; pay again to add time.`,
          tone: "success",
        };
    }
  }
  switch (e.reason) {
    case "institution_expired":
      return {
        headline: "Your institution's plan has ended",
        detail: `Ask the person who manages ${e.institution_name ?? "your institution"} to renew it.`,
        tone: "error",
      };
    case "seat_closed":
      return { headline: "This login has been closed", detail: "Ask your institution's manager about it.", tone: "error" };
    case "expired":
      return {
        headline: e.plan_code === "trial" ? "Your free trial has ended" : "Your plan has ended",
        detail: "Choose a plan below to carry on.",
        tone: "error",
      };
    default:
      return { headline: "No active plan", detail: "Choose a plan below to get started.", tone: "error" };
  }
}

function csvCell(value: string): string {
  // A leading = + - @ would run as a formula when the file is opened in Excel or Sheets.
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
}

/** Spreadsheet of new logins for the manager to hand out. */
export function credentialsCsv(institution: string, rows: readonly Credential[]): string {
  const head = ["Institution", "Name", "Login ID", "Password"].map(csvCell).join(",");
  const body = rows.map((r) => [institution, r.name, r.login_id, r.password].map(csvCell).join(","));
  return [head, ...body].join("\r\n") + "\r\n";
}

/** One name per line; blanks removed, repeated spaces collapsed. */
export function parseNames(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+/g, " ").trim())
    .filter((l) => l.length > 0);
}

/** How many days before the end the button starts asking people to renew. */
export const RENEW_WINDOW_DAYS = 7;

/**
 * The text of the flashing button, or null when it should not show. It shows to people who can
 * pay and either have no paid plan (trial or ended) or are about to run out. Never to staff,
 * institution logins (their manager pays) or people with plenty of paid time left.
 */
export function subscribeLabel(status: BillingStatus | null): string | null {
  if (!status || !status.can_purchase) return null;
  const e = status.entitlement;
  if (e.source === "staff") return null;
  if (!e.has_access) return "Subscribe to continue";
  if (e.source === "trial") return "Subscribe";
  if (e.source === "individual" && (e.days_left ?? Infinity) <= RENEW_WINDOW_DAYS) {
    return `Renew (${plural(e.days_left ?? 0, "day")} left)`;
  }
  if (e.source === "none") return "Subscribe";
  return null;
}

/**
 * "5000", "5,000" or "₦5,000.50" -> kobo. Null when it is not a positive amount with at most two
 * decimals. Used for the amount of a partial refund.
 */
export function parseNairaToKobo(text: string): number | null {
  const cleaned = text.replace(/[₦,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole, frac = ""] = cleaned.split(".");
  const kobo = Number(whole) * 100 + Number(frac.padEnd(2, "0"));
  return Number.isSafeInteger(kobo) && kobo > 0 ? kobo : null;
}
