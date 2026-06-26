import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Loader2, Download } from "lucide-react";
import { api, type Contractor } from "@/lib/api";
import { PageHeader, Stat as StatBox } from "@/components/ui-bits";
import { ContractorDrawer } from "@/components/drawer/ContractorDrawer";

// Vendors — drywall-material distributors, in their OWN section/tab (separate from
// contractors). Per-column filters like the Contractors page; small dataset so we
// fetch all and filter client-side.
// Show every column that the per-vendor detail box opens — the full Workstream E
// tag set + contact/identity fields — all at once across multiple vendors. The
// table scrolls horizontally; the same set is what Export CSV writes.
type Col = { key: string; label: string };
const COLS: Col[] = [
  { key: "business_name", label: "Distributor" },
  { key: "record_type", label: "Record" },
  { key: "canonical_network", label: "Network" },
  { key: "vendor_type", label: "Type" },
  { key: "state", label: "State" },
  { key: "county", label: "County" },
  { key: "city", label: "City" },
  { key: "city_tier", label: "Tier" },
  { key: "zip_code", label: "ZIP" },
  { key: "address", label: "Address" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "website", label: "Website" },
  { key: "license_status", label: "License" },
  { key: "source", label: "Source" },
  { key: "enrichment_status", label: "Enrichment" },
  { key: "out_of_territory", label: "Out of terr." },
  { key: "excluded_reason", label: "Excluded" },
  { key: "canonical_entity_id", label: "Entity ID" },
];

// Generic cell formatter for the plain (non-badge) columns.
function cellText(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "—";
  if (Array.isArray(v)) return v.length ? v.join("; ") : "—";
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${k}=${x}`).join("; ") || "—";
  return String(v);
}

export default function Vendors() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<Contractor | null>(null);

  const facets = useQuery({ queryKey: ["vendor-facets"], queryFn: () => api.vendorFacets() });
  const list = useQuery({
    queryKey: ["vendors-all"],
    queryFn: () => api.listVendors({ limit: 500, offset: 0 }),
  });

  const allRows = list.data?.rows ?? [];

  const rows = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => v.trim());
    if (!active.length) return allRows;
    return allRows.filter((r: any) =>
      active.every(([k, v]) => {
        const cell = k === "vendor_type" && r.is_big_box ? "big-box" : r[k];
        return String(cell ?? "").toLowerCase().includes(v.toLowerCase());
      }),
    );
  }, [allRows, filters]);

  const setF = (k: string, v: string) => setFilters((p) => ({ ...p, [k]: v }));

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Vendors"
        subtitle="Drywall-material distributors (the sell-to targets) — separate from contractors. Networks like GMS / L&W are rolled up; big-box stores are flagged."
        icon={<Boxes className="h-6 w-6 text-primary" />}
        actions={
          <button
            onClick={() => api.exportVendors({ format: "csv" })}
            className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-accent transition"
          >
            <Download className="h-4 w-4" /> Export CSV
          </button>
        }
      />

      <div className="grid grid-cols-3 gap-3 mb-5">
        <StatBox label="Vendors" value={facets.data?.total ?? allRows.length} icon={<Boxes className="h-3.5 w-3.5" />} />
        <StatBox label="Networks" value={facets.data?.networks.length ?? 0} icon={<Boxes className="h-3.5 w-3.5" />} />
        <StatBox label="Cities" value={facets.data?.cities.length ?? 0} icon={<Boxes className="h-3.5 w-3.5" />} />
      </div>

      {list.isLoading ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" /> Loading vendors…
        </div>
      ) : allRows.length === 0 ? (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No vendors yet. Run a Tennessee <b>Vendor</b> scrape from the Dashboard.
        </div>
      ) : (
        <div className="rounded-lg border bg-card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-xs uppercase text-muted-foreground">
              <tr>
                {COLS.map((c) => (
                  <th key={c.key} className="text-left px-3 py-2 font-medium whitespace-nowrap">{c.label}</th>
                ))}
              </tr>
              {/* Per-column filter row */}
              <tr className="bg-card">
                {COLS.map((c) => (
                  <th key={c.key} className="px-2 py-1.5">
                    <input
                      value={filters[c.key] ?? ""}
                      onChange={(e) => setF(c.key, e.target.value)}
                      placeholder="Filter…"
                      className="w-full min-w-[80px] rounded border bg-background px-2 py-1 text-xs font-normal normal-case"
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r.id} onClick={() => setSelected(r as Contractor)}
                    className="border-t hover:bg-accent/40 cursor-pointer whitespace-nowrap">
                  {COLS.map((c) => {
                    if (c.key === "business_name")
                      return <td key={c.key} className="px-3 py-2 font-medium">{r.business_name || "—"}</td>;
                    if (c.key === "vendor_type")
                      return (
                        <td key={c.key} className="px-3 py-2">
                          {r.is_big_box ? (
                            <span className="text-[10px] rounded bg-amber-100 text-amber-800 px-1.5 py-0.5">big-box</span>
                          ) : (
                            <span className="text-[10px] rounded bg-slate-100 text-slate-700 px-1.5 py-0.5">{r.vendor_type || "vendor"}</span>
                          )}
                        </td>
                      );
                    if (c.key === "city_tier")
                      return (
                        <td key={c.key} className="px-3 py-2">
                          {r.city_tier ? (
                            <span className={`text-[10px] font-bold rounded px-1.5 py-0.5 ${String(r.city_tier) === "1" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>Tier {r.city_tier}</span>
                          ) : "—"}
                        </td>
                      );
                    if (c.key === "excluded_reason")
                      return (
                        <td key={c.key} className="px-3 py-2">
                          {r.excluded_reason ? (
                            <span className="text-[10px] rounded bg-destructive/10 text-destructive px-1.5 py-0.5">{r.excluded_reason}</span>
                          ) : "—"}
                        </td>
                      );
                    if (c.key === "website")
                      return (
                        <td key={c.key} className="px-3 py-2 max-w-[200px] truncate">
                          {r.website ? <a className="text-primary hover:underline" href={r.website} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{r.website}</a> : "—"}
                        </td>
                      );
                    if (c.key === "canonical_entity_id")
                      return <td key={c.key} className="px-3 py-2 text-muted-foreground max-w-[160px] truncate"><code className="text-[11px]">{cellText(r[c.key])}</code></td>;
                    return <td key={c.key} className="px-3 py-2 text-muted-foreground max-w-[220px] truncate">{cellText(r[c.key])}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!list.isLoading && allRows.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          Showing {rows.length} of {allRows.length} vendors{Object.values(filters).some((v) => v.trim()) ? " (filtered)" : ""}.
        </p>
      )}

      <ContractorDrawer contractor={selected} open={!!selected} onClose={() => setSelected(null)} kind="vendor" />
    </div>
  );
}
