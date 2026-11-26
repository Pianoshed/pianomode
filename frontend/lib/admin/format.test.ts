import { refundWarning } from "@/lib/admin/api";
import { describe, expect, it } from "vitest";
import { describeAction } from "@/lib/admin/format";
import { groupSecret, recoveryCodesText } from "@/lib/account/format";

describe("audit log wording", () => {
  it("explains known actions with their details", () => {
    expect(describeAction({ action: "role_granted", detail: { role: "educator" } })).toBe("Gave a role (educator)");
    expect(describeAction({ action: "payment_recorded", detail: { plan: "individual", months: 3, reference: "manual_x" } })).toBe(
      "Recorded a payment made outside Paystack (individual, 3 months; ref manual_x)",
    );
    expect(describeAction({ action: "payment_refunded", detail: { reason: "paid twice", reference: "pp_1" } })).toContain("reason: paid twice");
  });
  it("never shows raw codes for unknown actions", () => {
    expect(describeAction({ action: "something_new_happened", detail: {} })).toBe("something new happened");
  });
});

describe("two-factor helpers", () => {
  it("groups the key in fours", () => {
    expect(groupSecret("JBSWY3DPEHPK3PXP")).toBe("JBSW Y3DP EHPK 3PXP");
    expect(groupSecret("jbsw y3dp")).toBe("jbsw y3dp");
  });
  it("writes the recovery codes file", () => {
    const t = recoveryCodesText(["abcde-fghjk", "mnpqr-stuvw"], "a@b.com");
    expect(t).toContain("Account: a@b.com");
    expect(t).toContain("abcde-fghjk\nmnpqr-stuvw");
  });
});

describe("refundWarning", () => {
  const base = { days_since_paid: 3, window_days: 14, outside_window: false, prior_refunds: 0, repeat: false, needs_override: false };
  it("says nothing for an ordinary refund", () => {
    expect(refundWarning(base)).toBeNull();
  });
  it("explains a late refund", () => {
    expect(refundWarning({ ...base, days_since_paid: 20, outside_window: true, needs_override: true })).toContain("20 days ago");
  });
  it("explains a repeat and can say both", () => {
    const w = refundWarning({ ...base, days_since_paid: 20, outside_window: true, prior_refunds: 2, repeat: true, needs_override: true });
    expect(w).toContain("already had 2 other payments");
    expect(w).toContain("20 days ago");
  });
});
