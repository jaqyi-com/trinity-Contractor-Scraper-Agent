import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Layers, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/ui-bits";

// Workstream E — view each pipeline stage's records, per batch.
// Stages = the scraper's actual phases: discovery → dedupe_seeds → classify → cap → enrich.
const STAGE_LABEL: Record<string, string> = {
  discovery: "1 · Discovery",
  dedupe_seeds: "2 · Dedupe",
  classify: "3 · Classify",
  cap: "4 · Cap",
  enrich: "5 · Enrich + Save",
};

export default function Stages() {
  const order = useQuery({ queryKey: ["stage-order"], queryFn: () => api.stageOrder() });
  const batches = useQuery({ queryKey: ["stage-batches"], queryFn: () => api.stageBatches() });

  const [batch, setBatch] = useState<string>("");
  const [stage, setStage] = useState<string>("discovery");

  // Default to the most recent batch once loaded.
  useEffect(() => {
    if (!batch && batches.data && batches.data.length) setBatch(batches.data[0].batch);
  }, [batches.data, batch]);

  const stageList = order.data?.stages ?? ["discovery", "dedupe_seeds", "classify", "cap", "enrich"];
  const current = batches.data?.find((b) => b.batch === batch);

  const records = useQuery({
    queryKey: ["stage-records", batch, stage],
    queryFn: () => api.stageRecords(batch, stage),
    enabled: !!batch,
  });

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Pipeline Stages"
        subtitle="Every scrape batch flows through stages: raw → normalized → enriched → filtered → deliverable. View what each stage produced."
        icon={<Layers className="h-6 w-6 text-primary" />}
      />

      {/* Batch picker */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <label className="text-sm font-medium">Batch</label>
        <select
          value={batch}
          onChange={(e) => setBatch(e.target.value)}
          className="rounded-md border bg-background px-3 py-2 text-sm min-w-[260px]"
        >
          {(batches.data ?? []).length === 0 && <option value="">No batches yet — run a scrape</option>}
          {(batches.data ?? []).map((b) => (
            <option key={b.batch} value={b.batch}>
              {b.batch_name}
            </option>
          ))}
        </select>
        {batches.isLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>

      {/* Stage tabs */}
      <div className="flex flex-wrap gap-1 border-b mb-4">
        {stageList.map((st) => {
          const count = current?.stages?.[st] ?? 0;
          const active = stage === st;
          return (
            <button
              key={st}
              onClick={() => setStage(st)}
              className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 transition ${
                active
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {STAGE_LABEL[st] ?? st}
              <span className="ml-1.5 text-[10px] rounded-full bg-muted px-1.5 py-0.5 text-muted-foreground">
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Records table */}
      {!batch ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          Run a scrape to see its pipeline stages here.
        </div>
      ) : records.isLoading ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" /> Loading {STAGE_LABEL[stage]} records…
        </div>
      ) : (records.data?.rows.length ?? 0) === 0 ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No records at the {STAGE_LABEL[stage]} stage for this batch.
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2">Business</th>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">State</th>
                <th className="text-left px-3 py-2">City</th>
                <th className="text-left px-3 py-2">Tier</th>
                <th className="text-left px-3 py-2">ZIP</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Excluded</th>
              </tr>
            </thead>
            <tbody>
              {records.data!.rows.map((r) => (
                <tr key={r.id} className="border-t hover:bg-accent/40">
                  <td className="px-3 py-2 font-medium">{r.business_name || "—"}</td>
                  <td className="px-3 py-2">{r.record_type}</td>
                  <td className="px-3 py-2">{r.state || "—"}</td>
                  <td className="px-3 py-2">{r.city || "—"}</td>
                  <td className="px-3 py-2">{r.city_tier ? `T${r.city_tier}` : "—"}</td>
                  <td className="px-3 py-2">{r.zip_code || "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{r.source || "—"}</td>
                  <td className="px-3 py-2">
                    {r.excluded_reason ? (
                      <span className="text-[10px] rounded bg-destructive/10 text-destructive px-1.5 py-0.5">
                        {r.excluded_reason}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {records.data && (
        <p className="mt-2 text-xs text-muted-foreground">
          {records.data.total} record{records.data.total === 1 ? "" : "s"} at the {STAGE_LABEL[stage]} stage.
        </p>
      )}
    </div>
  );
}
