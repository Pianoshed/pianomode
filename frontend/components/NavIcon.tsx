import {
  AudioWaveform,
  BookOpen,
  CreditCard,
  FileMusic,
  GraduationCap,
  LayoutDashboard,
  Building2,
  Library,
  ListMusic,
  Piano,
  Repeat,
  Settings,
  ShieldCheck,
  Users,
  Wallet,
} from "lucide-react";
import type { IconName } from "@/lib/nav";

const ICONS: Record<IconName, typeof Piano> = {
  dashboard: LayoutDashboard,
  piano: Piano,
  learn: GraduationCap,
  progressions: ListMusic,
  theory: BookOpen,
  midi: FileMusic,
  audio: AudioWaveform,
  practice: Repeat,
  library: Library,
  subscription: CreditCard,
  institution: Building2,
  billingAdmin: Wallet,
  people: Users,
  settings: Settings,
  admin: ShieldCheck,
};

export function NavIcon({ name, className = "h-5 w-5" }: { name: IconName; className?: string }) {
  const Icon = ICONS[name];
  return <Icon aria-hidden className={className} />;
}
