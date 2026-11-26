import { describe, expect, it } from "vitest";
import { credentialsCsv, describeEntitlement, formatNaira, parseNairaToKobo, parseNames } from "@/lib/billing/format";
import type { Entitlement } from "@/lib/billing/types";

const ent = (o: Partial<Entitlement>): Entitlement => ({
  has_access: true,
  source: "individual",
  plan_code: "individual",
  ends_at: "2026-12-14T12:00:00Z",
  days_left: 30,
  institution_name: null,
  reason: "ok",
  ...o,
});

describe("formatNaira", () => {
  it("formats whole naira with separators", () => {
    expect(formatNaira(1_500_000)).toBe("₦15,000");
    expect(formatNaira(8_000_000)).toBe("₦80,000");
    expect(formatNaira(15_000_000)).toBe("₦150,000");
    expect(formatNaira(0)).toBe("₦0");
  });
  it("keeps kobo when present", () => {
    expect(formatNaira(150_050)).toBe("₦1,500.50");
    expect(formatNaira(5)).toBe("₦0.05");
  });
});

describe("describeEntitlement", () => {
  it("counts trial days with correct plurals", () => {
    expect(describeEntitlement(ent({ source: "trial", plan_code: "trial", days_left: 1 })).headline).toBe("Free trial: 1 day left");
    expect(describeEntitlement(ent({ source: "trial", plan_code: "trial", days_left: 5 })).headline).toBe("Free trial: 5 days left");
  });
  it("tells the truth that plans do not renew by themselves", () => {
    expect(describeEntitlement(ent({})).detail).toMatch(/do not renew by themselves/);
  });
  it("sends seats to their manager, not to a payment screen", () => {
    const t = describeEntitlement(
      ent({ has_access: false, source: "none", reason: "institution_expired", institution_name: "Grace School" }),
    );
    expect(t.tone).toBe("error");
    expect(t.detail).toContain("Grace School");
    expect(t.detail).not.toMatch(/choose a plan/i);
  });
  it("distinguishes an ended trial from an ended plan", () => {
    expect(describeEntitlement(ent({ has_access: false, source: "none", reason: "expired", plan_code: "trial" })).headline).toMatch(/trial/);
    expect(describeEntitlement(ent({ has_access: false, source: "none", reason: "expired" })).headline).toBe("Your plan has ended");
  });
});

describe("credentialsCsv", () => {
  it("quotes cells and doubles inner quotes", () => {
    const csv = credentialsCsv('St "Mary"', [{ id: "1", name: "Ada, A.", login_id: "ABCD-001", password: "pw" }]);
    expect(csv.split("\r\n")[1]).toBe('"St ""Mary""","Ada, A.","ABCD-001","pw"');
  });
  it("defuses spreadsheet formulas in names", () => {
    const csv = credentialsCsv("S", [{ id: "1", name: "=HYPERLINK(1)", login_id: "A-1", password: "p" }]);
    expect(csv).toContain(`"'=HYPERLINK(1)"`);
  });
});

describe("parseNames", () => {
  it("drops blank lines and tidies spaces", () => {
    expect(parseNames("  Ada   Obi \n\n Tunde\r\n   \n")).toEqual(["Ada Obi", "Tunde"]);
  });
});

import { subscribeLabel } from "@/lib/billing/format";
import type { BillingStatus } from "@/lib/billing/types";

const st = (e: Partial<Entitlement>, can_purchase = true): BillingStatus => ({
  entitlement: ent(e),
  can_purchase,
  institution_role: null,
});

describe("subscribeLabel", () => {
  it("asks trial users to subscribe", () => {
    expect(subscribeLabel(st({ source: "trial", plan_code: "trial", days_left: 5 }))).toBe("Subscribe");
  });
  it("says so plainly when access has ended", () => {
    expect(subscribeLabel(st({ has_access: false, source: "none", reason: "expired" }))).toBe("Subscribe to continue");
  });
  it("asks paid users to renew only in the last week", () => {
    expect(subscribeLabel(st({ days_left: 7 }))).toBe("Renew (7 days left)");
    expect(subscribeLabel(st({ days_left: 1 }))).toBe("Renew (1 day left)");
    expect(subscribeLabel(st({ days_left: 8 }))).toBeNull();
  });
  it("never nags staff, institution logins or a signed-out page", () => {
    expect(subscribeLabel(st({ source: "staff", days_left: null }))).toBeNull();
    expect(subscribeLabel(st({ source: "institution", days_left: 2 }, false))).toBeNull();
    expect(subscribeLabel(st({ has_access: false, source: "none" }, false))).toBeNull();
    expect(subscribeLabel(null)).toBeNull();
  });
});

describe("parseNairaToKobo", () => {
  it("reads plain, comma and symbol amounts", () => {
    expect(parseNairaToKobo("5000")).toBe(500_000);
    expect(parseNairaToKobo("₦5,000.50")).toBe(500_050);
    expect(parseNairaToKobo(" 12.5 ")).toBe(1_250);
  });
  it("rejects anything that is not a positive amount", () => {
    for (const bad of ["", "0", "-5", "abc", "1.234", "1e5", "5,00,0x"]) expect(parseNairaToKobo(bad)).toBeNull();
  });
});
