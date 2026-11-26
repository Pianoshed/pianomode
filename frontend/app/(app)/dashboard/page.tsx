import type { Metadata } from "next";
import Link from "next/link";
import ApiStatus from "@/components/ApiStatus";
import { PageHeader } from "@/components/PageHeader";
import { ActivityBars } from "@/components/dashboard/ActivityBars";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { describeEntitlement } from "@/lib/billing/format";
import { getBillingStatus } from "@/lib/billing/server";
import { KIND_LABEL, relativeDay, studioHref } from "@/lib/library/format";
import { progressionHref, restoreProgression } from "@/lib/library/progression";
import { getDashboard } from "@/lib/library/server";

export const metadata: Metadata = { title: "Dashboard" };
export const dynamic = "force-dynamic";

const link = "font-medium underline underline-offset-4 hover:no-underline";

export default async function DashboardPage() {
  const [data, billing] = await Promise.all([getDashboard(), getBillingStatus()]);
  const plan = billing ? describeEntitlement(billing.entitlement) : null;

  return (
    <>
      <PageHeader title="Dashboard" description="Pick up where you left off." />
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Continue learning" className="md:col-span-2">
          {!data ? (
            <EmptyState>Could not load this just now. Refresh in a moment.</EmptyState>
          ) : data.continue_learning.length === 0 ? (
            <EmptyState>
              Lessons you start will appear here so you can resume them.{" "}
              <Link href="/learn" className="underline underline-offset-4">Browse lessons</Link>
            </EmptyState>
          ) : (
            <ul className="space-y-3">
              {data.continue_learning.map((l) => (
                <li key={l.id}>
                  <Link href={`/learn/${l.id}`} className={link}>{l.title}</Link>
                  <span className="ml-2 text-sm text-muted">
                    {l.goals_met} of {l.goals_total} practice goals met
                  </span>
                  <div className="mt-1 h-2 max-w-sm overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-label={`${l.title} progress`} aria-valuenow={l.progress_percent} aria-valuemin={0} aria-valuemax={100}>
                    <div className="h-full bg-accent" style={{ width: `${l.progress_percent}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Subscription">
          {plan ? (
            <div className="space-y-2">
              <p className="font-semibold">{plan.headline}</p>
              <p className="max-w-[56ch] text-sm text-muted">{plan.detail}</p>
              <Link href="/subscription" className="text-sm font-medium underline underline-offset-4">
                {billing?.can_purchase ? "Plans and payments" : "Details"}
              </Link>
            </div>
          ) : (
            <EmptyState>Could not load your plan just now.</EmptyState>
          )}
        </Card>

        <Card title="Practice activity">
          {!data || data.activity_total === 0 ? (
            <EmptyState>
              Practice passes and theory answers from the last 7 days are counted here.{" "}
              <Link href="/practice" className="underline underline-offset-4">Start practising</Link>
            </EmptyState>
          ) : (
            <ActivityBars days={data.activity} total={data.activity_total} />
          )}
        </Card>

        <Card title="Recent MIDI and audio projects">
          {!data || data.recent_projects.length === 0 ? (
            <EmptyState>Projects you save in MIDI Studio or the Audio Analyzer will be listed here.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {data.recent_projects.map((p) => (
                <li key={p.id}>
                  <Link href={studioHref(p.kind, p.id)} className={link}>{p.title}</Link>
                  <span className="ml-2 text-sm text-muted">{KIND_LABEL[p.kind]} · {relativeDay(p.opened_at)}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-sm"><Link href="/library" className="underline underline-offset-4">Open My Library</Link></p>
        </Card>

        <Card title="Saved chord progressions">
          {!data || data.saved_progressions.length === 0 ? (
            <EmptyState>Progressions you save will be listed here.</EmptyState>
          ) : (
            <ul className="space-y-2">
              {data.saved_progressions.map((p) => {
                const s = restoreProgression(p.data);
                return (
                  <li key={p.id}>
                    {s ? <Link href={progressionHref(s)} className={link}>{p.title}</Link> : <span className="font-medium">{p.title}</span>}
                    {s?.tonic ? <span className="ml-2 text-sm text-muted">in {s.tonic}</span> : null}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Recommended next" className="md:col-span-2">
          {!data ? (
            <EmptyState>Could not load this just now.</EmptyState>
          ) : data.recommended ? (
            <div className="space-y-1">
              <Link href={`/learn/${data.recommended.id}`} className={`${link} text-lg`}>{data.recommended.title}</Link>
              <p className="max-w-[64ch] text-sm text-muted">{data.recommended.summary}</p>
              <p className="text-sm">{data.recommended.reason}</p>
            </div>
          ) : (
            <EmptyState>You have started every lesson that is open to you. Finish the ones in progress, or revisit a lesson you practised.</EmptyState>
          )}
        </Card>
      </div>
      <div className="mt-8 text-muted">
        <ApiStatus />
      </div>
    </>
  );
}
