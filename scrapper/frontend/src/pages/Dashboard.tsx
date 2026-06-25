import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square, RotateCw, X, AlertTriangle, Save, Check } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import JobProgress from "@/components/JobProgress";

export default function Dashboard() {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const [conflictMsg, setConflictMsg] = useState<string | null>(null);
  // ─── Run scope: mode (contractor|vendor) + territory (FL|TN) ───
  const [mode, setMode] = useState<"contractor" | "vendor">("contractor");
  const [territory, setTerritory] = useState<"FL" | "TN">("FL");

  // ─── Run config: max final records per run (default 5000) ───
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() });
  const [maxRecords, setMaxRecords] = useState<string>("");
  // Per-service USD cost budgets. "" = unlimited (no cap).
  const [discoveryBudget, setDiscoveryBudget] = useState<string>("");
  const [bbbBudget, setBbbBudget] = useState<string>("");
  const [apolloBudget, setApolloBudget] = useState<string>("");
  // TN search radii (miles).
  const [vendorRadius, setVendorRadius] = useState<string>("");
  const [contractorRadius, setContractorRadius] = useState<string>("");
  // Optional statewide TN verify-a-name license enrichment (slow; default off).
  const [enableTnVerify, setEnableTnVerify] = useState(false);
  useEffect(() => {
    if (!settings.data) return;
    setMaxRecords(String(settings.data.max_final_records));
    const s = (v: number | null) => (v == null ? "" : String(v));
    setDiscoveryBudget(s(settings.data.discovery_budget_usd));
    setBbbBudget(s(settings.data.bbb_budget_usd));
    setApolloBudget(s(settings.data.apollo_budget_usd));
    setVendorRadius(String(settings.data.vendor_radius_miles));
    setContractorRadius(String(settings.data.contractor_radius_miles));
    setEnableTnVerify(!!settings.data.enable_tn_verify);
  }, [settings.data]);

  // "" → null (unlimited); a positive number → that budget; anything else → null.
  const parseBudget = (v: string): number | null => {
    const t = v.trim();
    if (t === "") return null;
    const n = Number(t);
    return Number.isFinite(n) && n > 0 ? n : null;
  };

  const saveSettings = useMutation({
    mutationFn: () =>
      api.updateSettings({
        max_final_records: Number(maxRecords),
        discovery_budget_usd: parseBudget(discoveryBudget),
        bbb_budget_usd: parseBudget(bbbBudget),
        apollo_budget_usd: parseBudget(apolloBudget),
        vendor_radius_miles: Number(vendorRadius) > 0 ? Number(vendorRadius) : null,
        contractor_radius_miles: Number(contractorRadius) > 0 ? Number(contractorRadius) : null,
        enable_tn_verify: enableTnVerify,
      }),
    onSuccess: (data) => {
      setMaxRecords(String(data.max_final_records));
      const s = (v: number | null) => (v == null ? "" : String(v));
      setDiscoveryBudget(s(data.discovery_budget_usd));
      setBbbBudget(s(data.bbb_budget_usd));
      setApolloBudget(s(data.apollo_budget_usd));
      setVendorRadius(String(data.vendor_radius_miles));
      setContractorRadius(String(data.contractor_radius_miles));
      setEnableTnVerify(!!data.enable_tn_verify);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const parsedMax = Number(maxRecords);
  const maxInvalid = !Number.isInteger(parsedMax) || parsedMax < 1 || parsedMax > 100000;
  // A non-empty budget that isn't a positive number is invalid.
  const budgetInvalid = [discoveryBudget, bbbBudget, apolloBudget].some(
    (v) => v.trim() !== "" && !(Number(v) > 0),
  );
  const radiusInvalid = [vendorRadius, contractorRadius].some(
    (v) => !(Number(v) > 0 && Number(v) <= 500),
  );
  const settingsUnchanged =
    settings.data &&
    parsedMax === settings.data.max_final_records &&
    parseBudget(discoveryBudget) === (settings.data.discovery_budget_usd ?? null) &&
    parseBudget(bbbBudget) === (settings.data.bbb_budget_usd ?? null) &&
    parseBudget(apolloBudget) === (settings.data.apollo_budget_usd ?? null) &&
    Number(vendorRadius) === settings.data.vendor_radius_miles &&
    Number(contractorRadius) === settings.data.contractor_radius_miles &&
    enableTnVerify === !!settings.data.enable_tn_verify;

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
    mutationFn: () => api.startJob({ mode, territory }),
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
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold mb-1">Dashboard</h1>
      <p className="text-muted-foreground mb-6">
        Start a scrape — pick what (contractors or vendors) and where (Florida or Tennessee).
        Runs in the background; stop and resume any time.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* ── Right column: run configuration ── */}
        <div className="lg:order-2 lg:col-span-1 p-5 rounded-lg border bg-card">
        <h2 className="font-semibold text-base mb-4">Run configuration</h2>
        <label htmlFor="max-records" className="block font-semibold mb-1">
          Max final records per run
        </label>
        <p className="text-xs text-muted-foreground mb-3">
          The pipeline returns at most this many deduplicated records (strongest tiers first).
          Bounds enrichment cost. Applies to the next run. Default{" "}
          {settings.data?.default_max_final_records ?? 5000}.
        </p>
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
        {maxInvalid && (
          <p className="text-xs text-destructive mt-2">Enter a whole number between 1 and 100,000.</p>
        )}

        {/* ─── Per-service cost budgets (USD). Blank = unlimited. ─── */}
        <div className="mt-6 pt-5 border-t">
          <p className="font-semibold mb-1">Cost limits per run (USD)</p>
          <p className="text-xs text-muted-foreground mb-4">
            Cap each paid service's spend for the next run. Leave a field{" "}
            <span className="font-medium">blank for unlimited</span>. Applies to the next run.
          </p>

          {([
            {
              label: "Apify — Google Maps (Discovery)",
              hint: "Hard cap enforced by Apify (min $0.50 per metro, so the effective floor is ~$0.50 × number of metros).",
              value: discoveryBudget,
              set: setDiscoveryBudget,
            },
            {
              label: "Apify — BBB (Enrichment)",
              hint: "~$0.12 per business. Budget ÷ $0.12 = how many top leads get a BBB lookup; the rest are skipped.",
              value: bbbBudget,
              set: setBbbBudget,
            },
            {
              label: "Apollo (Enrichment)",
              hint: "Estimated per-row cost. Budget ÷ per-row cost = how many top leads get Apollo email/owner enrichment.",
              value: apolloBudget,
              set: setApolloBudget,
            },
          ] as const).map((f) => {
            const inv = f.value.trim() !== "" && !(Number(f.value) > 0);
            return (
              <div key={f.label} className="mb-4">
                <label className="block text-sm font-medium mb-1">{f.label}</label>
                <p className="text-xs text-muted-foreground mb-2">{f.hint}</p>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">$</span>
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    placeholder="Unlimited"
                    value={f.value}
                    onChange={(e) => f.set(e.target.value)}
                    disabled={settings.isLoading}
                    className="w-40 rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                  />
                  <span className="text-xs text-muted-foreground">
                    {f.value.trim() === "" ? "→ unlimited" : ""}
                  </span>
                </div>
                {inv && (
                  <p className="text-xs text-destructive mt-1">Enter a positive amount, or leave blank for unlimited.</p>
                )}
              </div>
            );
          })}
        </div>

        {/* ─── TN search radii (miles) ─── */}
        <div className="mt-6 pt-5 border-t">
          <h3 className="text-sm font-semibold mb-1">Tennessee search radii (miles)</h3>
          <p className="text-xs text-muted-foreground mb-3">
            <b>Vendor radius</b> — when scraping vendors, search this far around each city center.
            <br />
            <b>Contractor radius</b> — when scraping TN contractors, search this far around each
            vendor account. Applies to the next run.
          </p>
          <div className="flex flex-wrap gap-6">
            {([
              { label: "Vendor radius", value: vendorRadius, set: setVendorRadius, def: "20" },
              { label: "Contractor radius", value: contractorRadius, set: setContractorRadius, def: "50" },
            ] as const).map((f) => {
              const inv = !(Number(f.value) > 0 && Number(f.value) <= 500);
              return (
                <div key={f.label}>
                  <label className="block text-sm font-medium mb-1">{f.label}</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      max={500}
                      step="1"
                      placeholder={f.def}
                      value={f.value}
                      onChange={(e) => f.set(e.target.value)}
                      disabled={settings.isLoading}
                      className="w-28 rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-50"
                    />
                    <span className="text-xs text-muted-foreground">miles</span>
                  </div>
                  {inv && <p className="text-xs text-destructive mt-1">1–500 miles.</p>}
                </div>
              );
            })}
          </div>
        </div>

        {/* ─── Optional: statewide TN verify-a-name license enrichment (default OFF) ─── */}
        <div className="mt-6 pt-5 border-t">
          <h3 className="text-sm font-semibold mb-1">Statewide TN license verify (optional)</h3>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={enableTnVerify}
              onChange={(e) => setEnableTnVerify(e.target.checked)}
              disabled={settings.isLoading}
              className="mt-1 h-4 w-4 shrink-0"
            />
            <span className="text-xs text-muted-foreground leading-relaxed">
              <span className="font-medium text-foreground">What this is:</span> Tennessee has no
              bulk-downloadable statewide license list — only a “check one name at a time” portal
              (verify.tn.gov). Normally TN runs use the free Nashville open-data list. Turn this ON to
              <span className="font-medium text-foreground"> also</span> look up each remaining business
              one-by-one on the statewide portal, for wider license coverage.
              <br />
              <span className="font-medium text-amber-700">⏱️ Cost = time:</span> it’s one web request
              <em> per business</em>, so a large TN run can take several extra minutes (it’s capped per
              run to stay bounded). It only adds license <span className="font-medium">enrichment</span> —
              it never changes which businesses are discovered, and a run never fails because of it.
              <br />
              <span className="font-medium text-foreground">Default: OFF.</span> Leave it off unless you
              specifically want the extra license matches and don’t mind the slower TN run. Florida runs
              are unaffected.
            </span>
          </label>
        </div>

        {/* ─── One Save for the whole card: max records + all budgets + radii ─── */}
        <div className="mt-6 pt-5 border-t flex items-center gap-3">
          <button
            onClick={() => saveSettings.mutate()}
            disabled={maxInvalid || budgetInvalid || radiusInvalid || settingsUnchanged || saveSettings.isPending || settings.isLoading}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {saveSettings.isSuccess && settingsUnchanged ? (
              <><Check className="h-4 w-4" /> Saved</>
            ) : (
              <><Save className="h-4 w-4" /> {saveSettings.isPending ? "Saving…" : "Save all settings"}</>
            )}
          </button>
          <span className="text-xs text-muted-foreground">
            Saves max records + all cost limits together.
          </span>
        </div>
        {saveSettings.isError && (
          <p className="text-xs text-destructive mt-2">{(saveSettings.error as Error).message}</p>
        )}
        </div>

      {/* ── Left column: run controls + live status ── */}
      <div className="lg:order-1 lg:col-span-2 space-y-5">

      {/* Conflict banner (refresh recovery) */}
      {conflictMsg && (
        <div className="mb-4 p-3 rounded-md border border-amber-200 bg-amber-50 text-amber-900 text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{conflictMsg}</span>
        </div>
      )}

      {/* ─── Run a scrape card ─── */}
      <div className="p-5 rounded-lg border bg-card">
      <h2 className="font-semibold text-base mb-4">Run a scrape</h2>
      {/* Run scope: mode + territory */}
      <div className="mb-5 flex flex-wrap gap-6">
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-1.5">What to scrape</div>
          <div className="inline-flex rounded-md border overflow-hidden">
            {(["contractor", "vendor"] as const).map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m);
                  if (m === "vendor") setTerritory("TN"); // vendors are TN-only (spec)
                }}
                disabled={startDisabled}
                className={`px-4 py-2 text-sm font-medium capitalize transition disabled:opacity-50 ${
                  mode === m ? "bg-primary text-primary-foreground" : "bg-card hover:bg-accent"
                }`}
              >
                {m === "contractor" ? "Contractors" : "Vendors"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs font-medium text-muted-foreground mb-1.5">Territory</div>
          <div className="inline-flex rounded-md border overflow-hidden">
            {(["FL", "TN"] as const).map((t) => {
              // Vendors are TN-only (spec) → Florida is disabled in vendor mode.
              const blocked = mode === "vendor" && t === "FL";
              return (
                <button
                  key={t}
                  onClick={() => setTerritory(t)}
                  disabled={startDisabled || blocked}
                  title={blocked ? "Vendor scraping is Tennessee-only" : undefined}
                  className={`px-4 py-2 text-sm font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${
                    territory === t ? "bg-primary text-primary-foreground" : "bg-card hover:bg-accent"
                  }`}
                >
                  {t === "FL" ? "Florida" : "Tennessee"}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      {mode === "contractor" && territory === "TN" && (
        <p className="mb-4 text-xs text-muted-foreground">
          TN contractor runs scrape the <b>contractor radius</b> around your vendor accounts. No
          vendor accounts yet? It falls back to scraping the TN cities directly (like Florida).
        </p>
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
              : `Start ${territory} ${mode === "vendor" ? "Vendor" : "Contractor"} Scrape`}
        </button>

        {/* Stop — only while running */}
        {isRunning && (
          <button
            onClick={() => stopJob.mutate()}
            disabled={stopJob.isPending || stopPending}
            className="inline-flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 text-amber-900 px-5 py-3 text-base font-semibold hover:bg-amber-100 disabled:opacity-60 transition"
          >
            <Square className="h-5 w-5" />
            {stopPending || stopJob.isPending ? "Finishing current stage…" : "Stop"}
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
      </div>{/* end run-a-scrape card */}

      {/* ─── Live status + animated phase progress ─── */}
      {s && (
        <div className="p-6 rounded-lg border bg-card">
          <div className="flex items-center justify-between mb-5 gap-3">
            <h3 className="font-semibold truncate">
              Job <span className="font-mono text-sm text-muted-foreground">{s.job_id}</span>
            </h3>
            {(stopPending || stopJob.isPending) && (
              <span className="text-xs text-amber-700 shrink-0 text-right max-w-xs">
                Stop will apply after the current stage finishes — its progress is
                saved, so Resume continues from there and you’re not charged again
                for this stage’s credits.
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
      </div>{/* end left column */}
      </div>{/* end grid */}
    </div>
  );
}
