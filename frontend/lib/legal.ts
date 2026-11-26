/**
 * Details the legal pages show. Set these when you build the web image (they are public):
 *   NEXT_PUBLIC_SUPPORT_EMAIL, NEXT_PUBLIC_COMPANY_NAME
 * Change LEGAL_UPDATED whenever the wording of a page changes.
 */
export const SUPPORT_EMAIL = process.env.NEXT_PUBLIC_SUPPORT_EMAIL ?? "";
export const COMPANY_NAME = process.env.NEXT_PUBLIC_COMPANY_NAME ?? "";
export const PRODUCT = "Keystudy";
export const LEGAL_UPDATED = "14 November 2026";

/** True until the owner's real contact details are filled in. */
export const legalDetailsMissing = !SUPPORT_EMAIL || !COMPANY_NAME;
