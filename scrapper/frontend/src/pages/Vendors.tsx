import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes, Loader2, Download } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader, Stat as StatBox } from "@/components/ui-bits";

// Vendors — drywall-material distributors, in their OWN section/tab (separate from
// contractors). Per-column filters like the Contractors page; small dataset so we
// fetch all and filter client-side.
type Col = { key: string; label: string };
const COLS: Col[] = [
  { key: "business_name", label: "Distributor" },
  { key: "canonical_network", label: "Network" },
  { key: "vendor_type", label: "Type" },
  { key: "address", label: "Address" },
  { key: "city", label: "City" },
  { key: "city_tier", label: "Tier" },
  { key: "zip_code", label: "ZIP" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "website", label: "Website" },
];

export default function Vendors() {
  const [filters, setFilters] = useState<Record<string, string>>({});

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
        const cell = r.key === "vendor_type" && r.is_big_box ? "big-box" : r[k];
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
                <tr key={r.id} className="border-t hover:bg-accent/40">
                  <td className="px-3 py-2 font-medium whitespace-nowrap">{r.business_name || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.canonical_network || "—"}</td>
                  <td className="px-3 py-2">
                    {r.is_big_box ? (
                      <span className="text-[10px] rounded bg-amber-100 text-amber-800 px-1.5 py-0.5">big-box</span>
                    ) : (
                      <span className="text-[10px] rounded bg-slate-100 text-slate-700 px-1.5 py-0.5">{r.vendor_type || "vendor"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 max-w-[200px] truncate text-muted-foreground">{r.address || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.city || "—"}</td>
                  <td className="px-3 py-2">
                    {r.city_tier ? (
                      <span className={`text-[10px] font-bold rounded px-1.5 py-0.5 ${r.city_tier === "1" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>Tier {r.city_tier}</span>
                    ) : "—"}
                  </td>
                  <td className="px-3 py-2">{r.zip_code || "—"}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{r.phone || "—"}</td>
                  <td className="px-3 py-2 max-w-[180px] truncate">{r.email || "—"}</td>
                  <td className="px-3 py-2 max-w-[200px] truncate">
                    {r.website ? <a className="text-primary hover:underline" href={r.website} target="_blank" rel="noreferrer">{r.website}</a> : "—"}
                  </td>
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
    </div>
  );
}
