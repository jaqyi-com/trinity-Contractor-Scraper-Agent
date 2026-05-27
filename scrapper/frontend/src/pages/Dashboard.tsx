import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Play, AlertTriangle } from "lucide-react";
import { api, ApiError } from "@/lib/api";

export default function Dashboard() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [conflictMsg, setConflictMsg] = useState<string | null>(null);

  // ─── Mount recovery: check if a job is already running ───
  // This handles: page refresh, new tab, browser restart.
  // If server reports an active job, we attach polling immediately.
  const currentJob = useQuery({
    queryKey: ["job-current"],
    queryFn: () => api.getCurrentJob(),
    staleTime: 0,
  });

  useEffect(() => {
    if (currentJob.data && currentJob.data.job_id && !jobId) {
      setJobId(currentJob.data.job_id);
    }
  }, [currentJob.data, jobId]);

  // ─── Start job mutation ───
  const startJob = useMutation({
    mutationFn: () => api.startJob(),
    onSuccess: (data) => {
      setJobId(data.job_id);
      setConflictMsg(null);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        // Server says a job is already running — attach to it
        const detail = err.detail?.detail || err.detail;
        const existingId = detail?.existing_job_id;
        if (existingId) {
          setJobId(existingId);
          setConflictMsg(
            `A job was already running (started ${detail.started_at}). Attached to existing job.`,
          );
        }
      }
    },
  });

  // ─── Live status polling ───
  const status = useQuery({
    queryKey: ["job-status", jobId],
    queryFn: () => api.getJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "completed" || s === "failed" || s === "interrupted" ? false : 2000;
    },
  });

  // ─── Button disable logic ───
  // Disabled when ANY job is active OR the request is in flight.
  const isActive =
    status.data?.status === "pending" || status.data?.status === "running";
  const buttonDisabled = isActive || startJob.isPending || currentJob.isLoading;

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
      <p className="text-muted-foreground mb-8">
        Start the full Florida contractor scrape pipeline. Pipeline runs 2-6 hours in background — no timeout.
      </p>

      {/* Conflict banner (refresh recovery) */}
      {conflictMsg && (
        <div className="mb-4 p-3 rounded-md border border-amber-200 bg-amber-50 text-amber-900 text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{conflictMsg}</span>
        </div>
      )}

      <button
        onClick={() => startJob.mutate()}
        disabled={buttonDisabled}
        className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-6 py-3 text-base font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
      >
        <Play className="h-5 w-5" />
        {isActive
          ? `Running... (${status.data?.status})`
          : startJob.isPending
            ? "Starting..."
            : "Start Full Scrape"}
      </button>

      {/* Generic error (non-409) */}
      {startJob.isError && !(startJob.error instanceof ApiError && startJob.error.status === 409) && (
        <div className="mt-4 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
          Error: {(startJob.error as Error).message}
        </div>
      )}

      {/* Live status panel */}
      {status.data && (
        <div className="mt-8 p-6 rounded-lg border bg-card">
          <h3 className="font-semibold mb-3">Job: {status.data.job_id}</h3>
          <div className="text-sm space-y-1">
            <div>
              Status: <span className="font-mono">{status.data.status}</span>
            </div>
            <div>
              Current stage: <span className="font-mono">{status.data.current_stage || "—"}</span>
            </div>
            <div>Started: {status.data.started_at}</div>
            {status.data.finished_at && <div>Finished: {status.data.finished_at}</div>}
            {status.data.error && (
              <div className="text-destructive">Error: {status.data.error}</div>
            )}
          </div>
          {status.data.stages_progress && (
            <pre className="mt-4 p-3 rounded bg-muted text-xs overflow-auto">
              {JSON.stringify(status.data.stages_progress, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
