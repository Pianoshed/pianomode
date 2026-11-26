import Link from "next/link";
import { KeyStrip } from "@/components/KeyStrip";

export function Brand({ href = "/dashboard" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 rounded-md">
      <KeyStrip octaves={1} highlight={[0, 4, 7]} className="h-7 w-10 shrink-0" />
      <span className="text-lg font-extrabold tracking-tight">Keystudy</span>
    </Link>
  );
}
