import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, AlertTriangle, Save, Check } from "lucide-react";
import { api, ApiError } from "@/lib/api";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [conflictMsg, setConflictMsg] = useState<string | null>(null);

  // ─── Run config: max final records per run (default 5000) ───
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });
  const [maxRecords, setMaxRecords] = useState<string>("");
  useEffect(() => {
    if (settings.data) setMaxRecords(String(settings.data.max_final_records));
  }, [settings.data]);

  const saveSettings = useMutation({
    mutationFn: () => api.updateSettings({ max_final_records: Number(maxRecords) }),
    onSuccess: (data) => {
      setMaxRecords(String(data.max_final_records));
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const parsedMax = Number(maxRecords);
  const maxInvalid = !Number.isInteger(parsedMax) || parsedMax < 1 || parsedMax > 100000;
  const maxUnchanged = settings.data && parsedMax === settings.data.max_final_records;

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

      {/* Run config — max final records per run */}
      <div className="mb-6 p-5 rounded-lg border bg-card max-w-md">
        <label htmlFor="max-records" className="block font-semibold mb-1">
          Max final records per run
        </label>
        <p className="text-xs text-muted-foreground mb-3">
          The pipeline returns at most this many deduplicated records (strongest tiers
          first). Bounds enrichment cost. Applies to the next run. Default{" "}
          {settings.data?.default_max_final_records ?? 5000}.
        </p>
        <div className="flex items-center gap-2">
          <input
            id="max-records"
            type="number"
            min={1}
            max={100000}
            value={maxRecords}
            onChange={(e) => setMaxRecords(e.target.value)}
            disabled={settings.isLoading}
            className="w-40 rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
          />
          <button
            onClick={() => saveSettings.mutate()}
            disabled={maxInvalid || maxUnchanged || saveSettings.isPending || settings.isLoading}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium hover:bg-secondary disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {saveSettings.isSuccess && maxUnchanged ? (
              <><Check className="h-4 w-4" /> Saved</>
            ) : (
              <><Save className="h-4 w-4" /> Save</>
            )}
          </button>
        </div>
        {maxInvalid && (
          <p className="text-xs text-destructive mt-2">Enter a whole number between 1 and 100,000.</p>
        )}
        {saveSettings.isError && (
          <p className="text-xs text-destructive mt-2">
            {(saveSettings.error as Error).message}
          </p>
        )}
      </div>

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
