"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export function SignOutButton({ name }: { name: string }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-line p-2 pl-3">
      <span className="min-w-0 truncate text-sm font-medium" title={name}>
        {name}
      </span>
      <button
        type="button"
        disabled={pending}
        onClick={async () => {
          setPending(true);
          await api("/api/v1/auth/logout", { method: "POST" });
          router.replace("/login");
          router.refresh();
        }}
        className="flex min-h-10 items-center gap-2 rounded-md px-3 text-sm text-muted hover:bg-surface-2 hover:text-fg disabled:opacity-50"
      >
        <LogOut aria-hidden className="h-4 w-4" />
        Sign out
      </button>
    </div>
  );
}
