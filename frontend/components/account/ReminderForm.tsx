"use client";

import { useState } from "react";
import { Notice } from "@/components/ui/Notice";
import { setReminderEmails } from "@/lib/billing/api";

export function ReminderForm({ initial }: { initial: boolean }) {
  const [on, setOn] = useState(initial);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function change(next: boolean) {
    setPending(true);
    setMessage(null);
    const r = await setReminderEmails(next);
    setPending(false);
    if (r.ok) {
      setOn(next);
      setMessage({ ok: true, text: next ? "You will get plan-ending emails." : "Plan-ending emails are off." });
    } else setMessage({ ok: false, text: r.message });
  }

  return (
    <div className="space-y-3">
      <label className="flex min-h-11 items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={on}
          disabled={pending}
          onChange={(e) => void change(e.target.checked)}
          className="mt-1 h-5 w-5"
        />
        <span>
          <span className="font-medium">Email me before my plan ends</span>
          <span className="block text-muted">One email 7, 3 and 1 days before, and one when it has ended.</span>
        </span>
      </label>
      {message ? <Notice tone={message.ok ? "success" : "error"}>{message.text}</Notice> : null}
    </div>
  );
}
