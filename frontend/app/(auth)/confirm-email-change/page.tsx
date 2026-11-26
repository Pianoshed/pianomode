import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthCard } from "@/components/auth/AuthCard";
import { ConfirmEmailChangePanel } from "@/components/auth/ConfirmEmailChangePanel";

export const metadata: Metadata = { title: "Confirm new email" };

export default function ConfirmEmailChangePage() {
  return (
    <AuthCard title="Confirm your new email">
      <Suspense>
        <ConfirmEmailChangePanel />
      </Suspense>
    </AuthCard>
  );
}
