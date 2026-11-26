import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ChangePasswordForm, DeactivateForm, ProfileForm } from "@/components/account/AccountForms";
import { PageHeader } from "@/components/PageHeader";
import { ChangeEmailForm, DataCard, DeleteAccountForm } from "@/components/account/EmailAndDataForms";
import { ReminderForm } from "@/components/account/ReminderForm";
import { TwoFactorForm } from "@/components/account/TwoFactorForm";
import { Card } from "@/components/ui/Card";
import { apiBase, apiHeaders } from "@/lib/server-api";
import { getCurrentUser } from "@/lib/user";

export const metadata: Metadata = { title: "Account Settings" };
export const dynamic = "force-dynamic";

type Identity = {
  email: string | null;
  login_id: string | null;
  reminder_emails?: boolean;
  two_factor_enabled?: boolean;
  two_factor_setup_needed?: boolean;
};

async function fetchIdentity(): Promise<Identity> {
  const res = await fetch(`${apiBase()}/api/v1/auth/me`, {
    headers: await apiHeaders(),
    cache: "no-store",
  });
  return res.ok
    ? ((await res.json()) as Identity)
    : { email: "", login_id: null };
}

export default async function SettingsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  const identity = await fetchIdentity();
  const isSeat = user.institutionRole === "seat";
  return (
    <>
      <PageHeader title="Account Settings" description="Your profile and sign-in details. Theme is in the menu." />
      <div className="grid max-w-xl gap-4">
        <ProfileForm
          initialName={user.name}
          email={identity.email ?? identity.login_id ?? ""}
          identifierLabel={isSeat ? "Login ID" : "Email"}
          hint={isSeat ? "Your institution gave you this. It is how you sign in." : "To change it, use Change email below."}
        />
        {isSeat ? null : (
          <Card title="Emails">
            <ReminderForm initial={identity.reminder_emails ?? true} />
          </Card>
        )}
        {isSeat ? null : <ChangeEmailForm current={identity.email ?? ""} />}
        <ChangePasswordForm />
        {isSeat ? null : (
          <TwoFactorForm
            enabled={identity.two_factor_enabled ?? false}
            setupNeeded={identity.two_factor_setup_needed ?? false}
            account={identity.email ?? ""}
          />
        )}
        {isSeat ? null : <DataCard />}
        {isSeat ? null : <DeactivateForm />}
        {isSeat ? null : <DeleteAccountForm needsCode={identity.two_factor_enabled ?? false} />}
      </div>
    </>
  );
}
