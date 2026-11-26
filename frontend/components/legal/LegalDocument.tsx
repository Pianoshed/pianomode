import Link from "next/link";
import type { ReactNode } from "react";
import { Notice } from "@/components/ui/Notice";
import { COMPANY_NAME, LEGAL_UPDATED, SUPPORT_EMAIL, legalDetailsMissing } from "@/lib/legal";

export function LegalDocument({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="max-w-[68ch] space-y-6">
      <header>
        <h1 className="text-3xl font-extrabold tracking-tight">{title}</h1>
        <p className="mt-1 text-sm text-muted">Last updated {LEGAL_UPDATED}</p>
      </header>
      {legalDetailsMissing ? (
        <Notice tone="error">
          The company name and support email are not set yet. Set NEXT_PUBLIC_COMPANY_NAME and
          NEXT_PUBLIC_SUPPORT_EMAIL when building the web image, and have these pages reviewed before
          launch.
        </Notice>
      ) : null}
      <div className="space-y-6 leading-relaxed [&_h2]:mb-2 [&_h2]:text-xl [&_h2]:font-bold [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5">
        {children}
      </div>
      <p className="border-t border-line pt-4 text-sm text-muted">
        Questions about this page: {SUPPORT_EMAIL ? <a className="underline underline-offset-4" href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a> : "(support email not set)"}
        {COMPANY_NAME ? `, ${COMPANY_NAME}` : ""}. See also <Link className="underline underline-offset-4" href="/terms">Terms</Link>,{" "}
        <Link className="underline underline-offset-4" href="/privacy">Privacy</Link> and{" "}
        <Link className="underline underline-offset-4" href="/refunds">Refunds</Link>.
      </p>
    </article>
  );
}
