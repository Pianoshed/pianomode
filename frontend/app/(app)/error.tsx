"use client";

import { Notice } from "@/components/ui/Notice";
import { buttonStyles } from "@/components/ui/button";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-start gap-4">
      <Notice tone="error">
        This page could not be loaded. Try again, and reload the browser tab if it keeps
        happening.
        {error.digest ? <span className="mt-1 block text-muted">Reference: {error.digest}</span> : null}
      </Notice>
      <button type="button" onClick={reset} className={buttonStyles({ variant: "secondary" })}>
        Try again
      </button>
    </div>
  );
}
