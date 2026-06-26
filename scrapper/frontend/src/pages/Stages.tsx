import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Layers, Loader2, Download } from "lucide-react";
import { api, type StageRecord } from "@/lib/api";
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

// Max columns we surface per record. Every stage row stores the FULL snapshot in
// `data`, so we read each field from data first, then fall back to the indexed
// top-level column. Same set the CSV export carries.
type Col = { key: string; label: string };
const COLS: Col[] = [
  { key: "business_name", label: "Business" },
  { key: "record_type", label: "Type" },
  { key: "state", label: "State" },
  { key: "county", label: "County" },
  { key: "city", label: "City" },
  { key: "city_tier", label: "Tier" },
  { key: "zip_code", label: "ZIP" },
  { key: "address", label: "Address" },
  { key: "canonical_network", label: "Network" },
  { key: "vendor_type", label: "Vendor type" },
  { key: "is_big_box", label: "Big-box" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "website", label: "Website" },
  { key: "license_status", label: "License" },
  { key: "tier", label: "Class tier" },
  { key: "source", label: "Source" },
  { key: "enrichment_status", label: "Enrichment" },
  { key: "out_of_territory", label: "Out of terr." },
  { key: "excluded_reason", label: "Excluded" },
  { key: "canonical_entity_id", label: "Entity ID" },
];

// Read a column from a stage row: full snapshot (`data`) first, then top-level.
function cell(r: StageRecord, key: string): string {
  const v = r.data && key in r.data ? r.data[key] : (r as any)[key];
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "—";
  if (Array.isArray(v)) return v.length ? v.join("; ") : "—";
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}=${x}`).join("; ") || "—";
  return String(v);
}

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

  const hasRows = (records.data?.rows.length ?? 0) > 0;

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Pipeline Stages"
        subtitle="Every scrape batch flows through stages: raw → normalized → enriched → filtered → deliverable. View — and download — the full record set each stage produced."
        icon={<Layers className="h-6 w-6 text-primary" />}
      />

      {/* Batch picker + download */}
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
        <button
          onClick={() => batch && api.exportStage(batch, stage)}
          disabled={!hasRows}
          className="ml-auto inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent transition disabled:opacity-40 disabled:cursor-not-allowed"
          title={hasRows ? "Download this stage as CSV (all columns)" : "Nothing to download at this stage"}
        >
          <Download className="h-4 w-4" /> Download CSV
        </button>
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
      ) : !hasRows ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No records at the {STAGE_LABEL[stage]} stage for this batch.
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className="text-left px-3 py-2 font-medium">{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {records.data!.rows.map((r) => (
                <tr key={r.id} className="border-t hover:bg-accent/40">
                  {COLS.map((c) => {
                    const val = cell(r, c.key);
                    if (c.key === "business_name")
                      return <td key={c.key} className="px-3 py-2 font-medium">{val}</td>;
                    if (c.key === "excluded_reason")
                      return (
                        <td key={c.key} className="px-3 py-2">
                          {val !== "—" ? (
                            <span className="text-[10px] rounded bg-destructive/10 text-destructive px-1.5 py-0.5">{val}</span>
                          ) : "—"}
                        </td>
                      );
                    if (c.key === "is_big_box" && val === "yes")
                      return <td key={c.key} className="px-3 py-2"><span className="text-[10px] rounded bg-amber-100 text-amber-800 px-1.5 py-0.5">big-box</span></td>;
                    if (c.key === "canonical_entity_id")
                      return <td key={c.key} className="px-3 py-2 text-muted-foreground max-w-[160px] truncate"><code className="text-[11px]">{val}</code></td>;
                    return <td key={c.key} className="px-3 py-2 text-muted-foreground max-w-[220px] truncate">{val}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {records.data && hasRows && (
        <p className="mt-2 text-xs text-muted-foreground">
          {records.data.total} record{records.data.total === 1 ? "" : "s"} at the {STAGE_LABEL[stage]} stage · {COLS.length} columns (scroll right) · Download CSV for the complete set.
        </p>
      )}
    </div>
  );
}
