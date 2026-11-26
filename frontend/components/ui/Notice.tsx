import { CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "info" | "success" | "error";

const tones: Record<Tone, { box: string; icon: typeof Info }> = {
  info: { box: "border-line bg-surface-2 text-fg", icon: Info },
  success: { box: "border-success/40 bg-success/10 text-fg", icon: CircleCheck },
  error: { box: "border-danger/40 bg-danger/10 text-fg", icon: TriangleAlert },
};

/** Errors use role="alert" so they are announced immediately; the rest use role="status". */
export function Notice({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  const { box, icon: Icon } = tones[tone];
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${box}`}
    >
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="max-w-[64ch]">{children}</div>
    </div>
  );
}
