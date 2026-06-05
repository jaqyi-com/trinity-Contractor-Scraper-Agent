import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square, RotateCw, X, AlertTriangle, Save, Check } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import JobProgress from "@/components/JobProgress";

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

  // ─── Mount recovery: attach to an already-active job (running OR paused) ───
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

  // ─── Live status polling ───
  const status = useQuery({
    queryKey: ["job-status", jobId],
    queryFn: () => api.getJobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "completed" || s === "failed" || s === "cancelled" ? false : 2000;
    },
  });

  const s = status.data;
  const isRunning = s?.status === "pending" || s?.status === "running";
  const isPaused = s?.status === "paused";
  const isFailed = s?.status === "failed";
  const isDone = s?.status === "completed";
  const stopPending = !!s?.stop_requested && isRunning;

  // ─── Mutations ───
  const startJob = useMutation({
    mutationFn: () => api.startJob(),
    onSuccess: (data) => {
      setJobId(data.job_id);
      setConflictMsg(null);
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        const detail = err.detail?.detail || err.detail;
        const existingId = detail?.existing_job_id;
        if (existingId) {
          setJobId(existingId);
          setConflictMsg(`A job was already active (status ${detail.status}). Attached to it.`);
        }
      }
    },
  });

  const refetchStatus = () =>
    queryClient.invalidateQueries({ queryKey: ["job-status", jobId] });

  const stopJob = useMutation({
    mutationFn: () => api.stopJob(jobId!),
    onSuccess: refetchStatus,
  });
  const resumeJob = useMutation({
    mutationFn: () => api.resumeJob(jobId!),
    onSuccess: refetchStatus,
  });
  const cancelJob = useMutation({
    mutationFn: () => api.cancelJob(jobId!),
    onSuccess: () => {
      refetchStatus();
      queryClient.invalidateQueries({ queryKey: ["job-current"] });
    },
  });

  const startDisabled =
    isRunning || isPaused || startJob.isPending || currentJob.isLoading || resumeJob.isPending;

  // Total metros — for the discovery sub-progress %.
  const cities = useQuery({ queryKey: ["cities"], queryFn: () => api.listCities() });
  const totalMetros = cities.data?.length;

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <h1 className="text-3xl font-bold mb-2">Dashboard</h1>
      <p className="text-muted-foreground mb-8">
        Start the full Florida contractor scrape pipeline. Runs in the background — stop and
        resume any time without re-running the expensive discovery stage.
      </p>

      {/* Run config — max final records per run */}
      <div className="mb-6 p-5 rounded-lg border bg-card max-w-md">
        <label htmlFor="max-records" className="block font-semibold mb-1">
          Max final records per run
        </label>
        <p className="text-xs text-muted-foreground mb-3">
          The pipeline returns at most this many deduplicated records (strongest tiers first).
          Bounds enrichment cost. Applies to the next run. Default{" "}
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
          <p className="text-xs text-destructive mt-2">{(saveSettings.error as Error).message}</p>
        )}
      </div>

      {/* Conflict banner (refresh recovery) */}
      {conflictMsg && (
        <div className="mb-4 p-3 rounded-md border border-amber-200 bg-amber-50 text-amber-900 text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{conflictMsg}</span>
        </div>
      )}

      {/* ─── Action buttons ─── */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => startJob.mutate()}
          disabled={startDisabled}
          className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-6 py-3 text-base font-semibold hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <Play className="h-5 w-5" />
          {isRunning
            ? `Running... (${s?.status})`
            : startJob.isPending
              ? "Starting..."
              : "Start Full Scrape"}
        </button>

        {/* Stop — only while running */}
        {isRunning && (
          <button
            onClick={() => stopJob.mutate()}
            disabled={stopJob.isPending || stopPending}
            className="inline-flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 text-amber-900 px-5 py-3 text-base font-semibold hover:bg-amber-100 disabled:opacity-60 transition"
          >
            <Square className="h-5 w-5" />
            {stopPending ? "Stopping now..." : "Stop"}
          </button>
        )}

        {/* Resume + Cancel — when paused or failed */}
        {(isPaused || isFailed) && (
          <>
            <button
              onClick={() => resumeJob.mutate()}
              disabled={resumeJob.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-5 py-3 text-base font-semibold hover:bg-primary/90 disabled:opacity-50 transition"
            >
              <RotateCw className="h-5 w-5" />
              {resumeJob.isPending ? "Resuming..." : `Resume${s?.resume_from ? ` (${s.resume_from})` : ""}`}
            </button>
            {isPaused && (
              <button
                onClick={() => cancelJob.mutate()}
                disabled={cancelJob.isPending}
                className="inline-flex items-center gap-2 rounded-md border border-destructive/30 text-destructive px-5 py-3 text-base font-semibold hover:bg-destructive/10 disabled:opacity-50 transition"
              >
                <X className="h-5 w-5" />
                {cancelJob.isPending ? "Cancelling..." : "Cancel"}
              </button>
            )}
          </>
        )}
      </div>

      {/* Generic start error (non-409) */}
      {startJob.isError && !(startJob.error instanceof ApiError && startJob.error.status === 409) && (
        <div className="mt-4 p-3 rounded-md bg-destructive/10 text-destructive text-sm">
          Error: {(startJob.error as Error).message}
        </div>
      )}

      {/* ─── Live status + animated phase progress ─── */}
      {s && (
        <div className="mt-8 p-6 rounded-lg border bg-card">
          <div className="flex items-center justify-between mb-5 gap-3">
            <h3 className="font-semibold truncate">
              Job <span className="font-mono text-sm text-muted-foreground">{s.job_id}</span>
            </h3>
            {stopPending && (
              <span className="text-xs text-amber-700 shrink-0">
                Stopping now — current stage is discarded and will re-run from start on resume
              </span>
            )}
          </div>

          <JobProgress job={s} totalMetros={totalMetros} />

          <div className="mt-5 border-t pt-4 text-sm space-y-1 text-muted-foreground">
            <div>Current stage: <span className="font-mono text-foreground">{s.current_stage || "—"}</span></div>
            <div>Started: {s.started_at}</div>
            {s.finished_at && <div>Finished: {s.finished_at}</div>}
            {s.error && <div className="text-destructive">Error: {s.error}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
