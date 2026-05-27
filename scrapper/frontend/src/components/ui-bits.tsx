// Small presentational primitives shared by tables and drawers.

import { cn } from "@/lib/utils";

export function Badge({
  children,
  variant = "default",
  className,
}: {
  children: React.ReactNode;
  variant?: "default" | "success" | "danger" | "warning" | "info" | "muted";
  className?: string;
}) {
  const styles: Record<string, string> = {
    default: "bg-secondary text-secondary-foreground",
    success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    danger: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
    warning: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
    info: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
    muted: "bg-muted text-muted-foreground border",
  };
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", styles[variant], className)}>
      {children}
    </span>
  );
}

export function tierVariant(tier?: string | null): "success" | "info" | "warning" | "danger" | "muted" {
  if (!tier) return "muted";
  if (tier.startsWith("TIER_1")) return "success";
  if (tier.startsWith("TIER_2")) return "info";
  if (tier.startsWith("TIER_3")) return "warning";
  if (tier.startsWith("EXCLUDE")) return "danger";
  return "muted";
}

export function licenseVariant(status?: string | null): "success" | "warning" | "danger" | "muted" {
  if (!status) return "muted";
  const s = status.toLowerCase();
  if (s.includes("active") || s.includes("current")) return "success";
  if (s.includes("expired") || s.includes("inactive")) return "warning";
  if (s.includes("unlicensed") || s.includes("revoked")) return "danger";
  return "muted";
}

export function decisionVariant(d?: string | null): "success" | "danger" | "muted" {
  if (d === "INCLUDED") return "success";
  if (d === "EXCLUDED") return "danger";
  return "muted";
}

export function PageHeader({
  title,
  subtitle,
  icon,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between mb-5 gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
          {icon}
          {title}
        </h1>
        {subtitle && <p className="text-sm text-muted-foreground mt-1 max-w-2xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  icon,
  variant = "default",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  variant?: "default" | "success" | "danger" | "info";
}) {
  const ring: Record<string, string> = {
    default: "",
    success: "ring-1 ring-emerald-200 dark:ring-emerald-900/40",
    danger: "ring-1 ring-red-200 dark:ring-red-900/40",
    info: "ring-1 ring-sky-200 dark:ring-sky-900/40",
  };
  return (
    <div className={cn("rounded-lg border bg-card p-4", ring[variant])}>
      <div className="flex items-center gap-2 text-muted-foreground text-[11px] uppercase tracking-wide font-semibold">
        {icon}
        {label}
      </div>
      <div className="text-2xl font-bold mt-1 tabular-nums">{value}</div>
      {hint && <div className="text-xs text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}

export function EmptyValue() {
  return <span className="text-muted-foreground/60">—</span>;
}
