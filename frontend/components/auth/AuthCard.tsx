import type { ReactNode } from "react";

export function AuthCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="w-full max-w-md rounded-xl border border-line bg-surface p-6 sm:p-8">
      <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
      {description ? <p className="mt-2 text-muted">{description}</p> : null}
      <div className="mt-6 space-y-4">{children}</div>
    </div>
  );
}
