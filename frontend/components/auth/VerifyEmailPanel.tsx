"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { useAction } from "@/components/auth/useAction";
import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";
import { api } from "@/lib/api";

export function VerifyEmailPanel() {
  const token = useSearchParams().get("token");
  const { pending, error, run } = useAction();
  const [done, setDone] = useState(false);

  if (!token) {
    return <Notice tone="error">This link is missing its token. Open the link from your email again.</Notice>;
  }
  if (done) {
    return (
      <div className="space-y-4">
        <Notice tone="success">Email verified. You can sign in now.</Notice>
        <Link href="/login" className={buttonStyles()}>Sign in</Link>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {error ? <Notice tone="error">{error}</Notice> : null}
      <button
        type="button"
        disabled={pending}
        className={buttonStyles()}
        onClick={async () => {
          const r = await run(() => api("/api/v1/auth/verify-email", { method: "POST", body: { token } }));
          if (r.ok) setDone(true);
        }}
      >
        {pending ? "Verifying…" : "Verify my email"}
      </button>
    </div>
  );
}
