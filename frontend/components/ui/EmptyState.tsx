import type { ReactNode } from "react";

/** Says what will appear here and, when something can be done, how to start. */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg bg-surface-2 p-4 text-sm text-muted">
      <p className="max-w-[56ch]">{children}</p>
      {action}
    </div>
  );
}
