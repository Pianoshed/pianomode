"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { confirmEmailChange } from "@/lib/account/api";

export function ConfirmEmailChangePanel() {
  const token = useSearchParams().get("token");
  const { pending, error, run } = useAction();
  const [done, setDone] = useState(false);

  if (!token) return <Notice tone="error">This link is missing its token. Open the link from your email again.</Notice>;
  if (done) {
    return (
      <div className="space-y-4">
        <Notice tone="success">Your email was changed. Sign in again with the new address.</Notice>
        <Link href="/login" className={buttonStyles()}>Sign in</Link>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      <button type="button" disabled={pending} className={buttonStyles()} onClick={async () => { const r = await run(() => confirmEmailChange(token)); if (r.ok) setDone(true); }}>
        {pending ? "Confirming…" : "Confirm my new email"}
      </button>
    </div>
  );
}
