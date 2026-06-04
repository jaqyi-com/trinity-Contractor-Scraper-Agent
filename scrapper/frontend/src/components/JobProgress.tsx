// JobProgress — animated, interactive pipeline progress for the Dashboard.
// Replaces the raw stages_progress JSON dump with an overall progress bar + a
// per-phase timeline that surfaces each stage's real metrics.

import { Badge } from "./ui-bits";
import { cn } from "@/lib/utils";
import {
  Check, Loader2, Pause, Search, Layers, Tag, Filter, Sparkles, GitMerge,
  ChevronRight,
} from "lucide-react";

type Prog = Record<string, any>;
type Job = {
  status?: string;
  current_stage?: string;
  resume_from?: string | null;
  stop_requested?: boolean;
  stages_progress?: Prog;
};

const PHASES = [
  { key: "discovery", label: "Discovery", icon: Search, desc: "Google Maps scrape across metros" },
  { key: "dedupe_seeds", label: "Dedupe seeds", icon: Layers, desc: "Collapse duplicates before paid enrichment" },
  { key: "classify", label: "Classify", icon: Tag, desc: "Tier each business via the keyword classifier" },
  { key: "cap", label: "Cap", icon: Filter, desc: "Keep the strongest N leads" },
  { key: "enrich", label: "DBPR + Enrich", icon: Sparkles, desc: "License match + BBB/Apollo + save" },
  { key: "dedupe_final", label: "Final dedupe", icon: GitMerge, desc: "Post-insert duplicate sweep" },
];

function phaseIndex(stage?: string): number {
  if (!stage) return -1;
  if (stage.startsWith("discovery")) return 0;
  if (stage === "dedupe_seeds") return 1;
  if (stage === "classify") return 2;
  if (stage === "cap") return 3;
  if (stage === "enrich") return 4;
  if (stage === "dedupe") return 5; // backend uses "dedupe" for the final sweep
  if (stage === "completed") return PHASES.length;
  return -1;
}

const n = (v: any) => (typeof v === "number" ? v.toLocaleString() : v);

/** Small metric pill (label + value). */
function Metric({ label, value, tone = "default" }: { label: string; value: React.ReactNode; tone?: "default" | "good" | "muted" | "warn" }) {
  const toneCls: Record<string, string> = {
    default: "bg-secondary text-secondary-foreground",
    good: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
    muted: "bg-muted text-muted-foreground",
    warn: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  };
  return (
    <span className={cn("inline-flex items-baseline gap-1 rounded-md px-2 py-1 text-xs", toneCls[tone])}>
      <span className="opacity-70">{label}</span>
      <span className="font-semibold tabular-nums">{value}</span>
    </span>
  );
}

/** Render the metrics for one phase from stages_progress. */
function PhaseMetrics({ phaseKey, prog }: { phaseKey: string; prog: Prog }) {
  if (phaseKey === "discovery") {
    const metros = Object.entries(prog)
      .filter(([k]) => k.startsWith("discovery:"))
      .map(([k, v]) => ({ name: k.slice("discovery:".length), seeds: v?.seeds ?? 0 }));
    if (!metros.length) return null;
    const totalSeeds = metros.reduce((a, m) => a + (m.seeds || 0), 0);
    return (
      <div className="space-y-2">
        <Metric label="seeds found" value={n(totalSeeds)} tone="good" />
        <div className="flex flex-wrap gap-1.5">
          {metros.map((m) => (
            <span key={m.name} className="inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-[11px]">
              <Check className="h-3 w-3 text-emerald-500" />
              {m.name}
              <span className="font-semibold tabular-nums text-muted-foreground">{n(m.seeds)}</span>
            </span>
          ))}
        </div>
      </div>
    );
  }
  const p = prog[phaseKey];
  if (!p) return null;
  if (phaseKey === "dedupe_seeds")
    return (
      <div className="flex flex-wrap gap-1.5">
        <Metric label="raw" value={n(p.raw)} tone="muted" />
        <Metric label="unique" value={n(p.unique)} tone="good" />
        <Metric label="dupes removed" value={n(p.removed)} tone="warn" />
      </div>
    );
  if (phaseKey === "classify")
    return (
      <div className="flex flex-wrap gap-1.5">
        <Metric label="scanned" value={n(p.scanned)} tone="muted" />
        <Metric label="included" value={n(p.included)} tone="good" />
        <Metric label="excluded" value={n(p.excluded)} tone="warn" />
      </div>
    );
  if (phaseKey === "cap")
    return (
      <div className="flex flex-wrap gap-1.5">
        <Metric label="limit" value={n(p.limit)} tone="muted" />
        <Metric label="kept" value={n(p.kept)} tone="good" />
        <Metric label="dropped" value={n(p.dropped)} tone="warn" />
      </div>
    );
  if (phaseKey === "enrich")
    return (
      <div className="flex flex-wrap gap-1.5">
        <Metric label="saved" value={n(p.saved)} tone="good" />
      </div>
    );
  if (phaseKey === "dedupe_final" && p.status)
    return <Metric label="status" value={p.status} tone="good" />;
  return null;
}

export default function JobProgress({ job, totalMetros }: { job: Job; totalMetros?: number }) {
  const prog = job.stages_progress || {};
  const isRunning = job.status === "pending" || job.status === "running";
  const isPaused = job.status === "paused";
  const isFailed = job.status === "failed";
  const isDone = job.status === "completed";
  const isCancelled = job.status === "cancelled";

  // Which phase is "current".
  let activeIdx: number;
  if (isDone) activeIdx = PHASES.length;
  else if (isPaused || isFailed) activeIdx = Math.max(0, PHASES.findIndex((p) => p.key === job.resume_from));
  else activeIdx = phaseIndex(job.current_stage);

  // Overall percentage (with a partial bump for in-progress discovery).
  const metrosDone = Object.keys(prog).filter((k) => k.startsWith("discovery:")).length;
  let pct: number;
  if (isDone) pct = 100;
  else if (isCancelled) pct = (Math.max(0, activeIdx) / PHASES.length) * 100;
  else {
    const base = Math.max(0, activeIdx) / PHASES.length;
    let partial = 0;
    if (activeIdx === 0 && totalMetros) partial = Math.min(metrosDone / totalMetros, 1) / PHASES.length;
    pct = Math.min(99, (base + partial) * 100);
  }

  const barColor = isFailed
    ? "from-red-500 to-red-400"
    : isPaused
      ? "from-amber-500 to-amber-400"
      : isDone
        ? "from-emerald-500 to-emerald-400"
        : "from-sky-500 to-emerald-500";

  return (
    <div>
      {/* Overall bar */}
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-medium">
          {isDone ? "Completed" : isCancelled ? "Cancelled" : isPaused ? "Paused" : isFailed ? "Failed" : "In progress"}
        </span>
        <span className="tabular-nums text-muted-foreground">{Math.round(pct)}%</span>
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full bg-gradient-to-r transition-all duration-700 ease-out", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Phase timeline */}
      <ol className="relative mt-6 space-y-1">
        {PHASES.map((p, i) => {
          const done = i < activeIdx;
          const active = i === activeIdx && isRunning;
          const pausedHere = i === activeIdx && (isPaused || isFailed);
          const pending = i > activeIdx && !done;
          const Icon = p.icon;
          const last = i === PHASES.length - 1;

          return (
            <li key={p.key} className="relative flex gap-4 pb-5">
              {/* connector line */}
              {!last && (
                <span
                  className={cn(
                    "absolute left-[15px] top-8 h-full w-0.5",
                    done ? "bg-emerald-400" : "bg-border",
                  )}
                />
              )}
              {/* status dot */}
              <span
                className={cn(
                  "z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-4 ring-card transition-colors",
                  done
                    ? "bg-emerald-500 text-white"
                    : active
                      ? "bg-sky-500 text-white"
                      : pausedHere
                        ? "bg-amber-500 text-white"
                        : "bg-muted text-muted-foreground",
                )}
              >
                {done ? (
                  <Check className="h-4 w-4" />
                ) : active ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : pausedHere ? (
                  <Pause className="h-4 w-4" />
                ) : (
                  <Icon className="h-4 w-4" />
                )}
              </span>

              {/* content */}
              <div className={cn("flex-1 min-w-0", pending && "opacity-55")}>
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold leading-tight">{p.label}</h4>
                  {active && <Badge variant="info">running</Badge>}
                  {done && <Badge variant="success">done</Badge>}
                  {pausedHere && <Badge variant="warning">{isFailed ? "failed here" : "resume here"}</Badge>}
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">{p.desc}</p>
                {(done || active || pausedHere) && (
                  <div className="mt-2">
                    <PhaseMetrics phaseKey={p.key} prog={prog} />
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Raw JSON — collapsed, for debugging */}
      <details className="mt-2 group">
        <summary className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground hover:text-foreground select-none">
          <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
          Raw progress data
        </summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded bg-muted p-3 text-xs">
          {JSON.stringify(prog, null, 2)}
        </pre>
      </details>
    </div>
  );
}
