import { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { FileText, Search, X, CheckCircle, XCircle } from "lucide-react";
import { api, type ClassificationLog } from "@/lib/api";
import { DataTable, sortingToParams } from "@/components/grid/DataTable";
import { FilterChip } from "@/components/grid/FilterChip";
import { LogDrawer } from "@/components/drawer/LogDrawer";
import { Badge, tierVariant, decisionVariant, PageHeader, Stat, EmptyValue } from "@/components/ui-bits";

export default function Logs() {
  const [search, setSearch] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<string[]>([]);
  const [tierFilter, setTierFilter] = useState<string[]>([]);

  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);

  const [selected, setSelected] = useState<ClassificationLog | null>(null);

  const sortParams = sortingToParams(sorting, { sort_by: "created_at", sort_dir: "desc" });

  const facets = useQuery({
    queryKey: ["log-facets"],
    queryFn: () => api.classificationFacets(),
  });

  const query = useQuery({
    queryKey: ["logs", { search, decisionFilter, tierFilter, sortParams, pageIndex, pageSize }],
    queryFn: () =>
      api.listClassificationLog({
        search: search.trim() || undefined,
        decision: decisionFilter,
        tier: tierFilter,
        sort_by: sortParams.sort_by,
        sort_dir: sortParams.sort_dir,
        limit: pageSize,
        offset: pageIndex * pageSize,
      }),
    placeholderData: keepPreviousData,
  });

  function resetPage() { if (pageIndex !== 0) setPageIndex(0); }

  const activeFilterCount =
    decisionFilter.length + tierFilter.length + (search.trim() ? 1 : 0);

  function clearAll() {
    setSearch(""); setDecisionFilter([]); setTierFilter([]); setPageIndex(0);
  }

  // Headline counts come from the facets endpoint (full-corpus, not filtered)
  const included = facets.data?.decisions?.find((d) => d.value === "INCLUDED")?.n ?? 0;
  const excluded = facets.data?.decisions?.find((d) => d.value === "EXCLUDED")?.n ?? 0;
  const total = facets.data?.total ?? 0;
  const inclRate = total ? Math.round((included / total) * 100) : 0;

  const columns = useMemo<ColumnDef<ClassificationLog, any>[]>(() => [
    { id: "business_name", accessorKey: "business_name", header: "Business",
      cell: ({ row }) => (
        <div className="min-w-[200px]">
          <div className="font-medium">{row.original.business_name || <EmptyValue />}</div>
          {row.original.place_id && <div className="text-[10px] text-muted-foreground font-mono truncate max-w-[260px]">{row.original.place_id}</div>}
        </div>
      ),
    },
    { id: "decision", accessorKey: "decision", header: "Decision",
      cell: ({ getValue }) => <Badge variant={decisionVariant(getValue() as string)}>{getValue() as string}</Badge>,
    },
    { id: "assigned_tier", accessorKey: "assigned_tier", header: "Tier",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <Badge variant={tierVariant(v)}>{v}</Badge> : <EmptyValue />;
      },
    },
    { id: "matched", enableSorting: false, header: "Matched",
      cell: ({ row }) => {
        const km = row.original.matched_keywords;
        if (!km?.length) return <EmptyValue />;
        const shown = km.slice(0, 3);
        const more = km.length - shown.length;
        return (
          <div className="flex flex-wrap gap-1 max-w-[260px]">
            {shown.map((k, i) => <Badge key={i} variant="success">{k.keyword}</Badge>)}
            {more > 0 && <Badge variant="muted">+{more}</Badge>}
          </div>
        );
      },
    },
    { id: "exclusion", enableSorting: false, header: "Exclusion",
      cell: ({ row }) => {
        const km = row.original.exclusion_keywords;
        if (!km?.length) return <EmptyValue />;
        const shown = km.slice(0, 2);
        const more = km.length - shown.length;
        return (
          <div className="flex flex-wrap gap-1 max-w-[200px]">
            {shown.map((k, i) => <Badge key={i} variant="danger">{k.keyword}</Badge>)}
            {more > 0 && <Badge variant="muted">+{more}</Badge>}
          </div>
        );
      },
    },
    { id: "created_at", accessorKey: "created_at", header: "When",
      cell: ({ getValue }) => (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {new Date(getValue() as string).toLocaleString()}
        </span>
      ),
    },
  ], []);

  return (
    <div className="p-6 max-w-[1500px] mx-auto">
      <PageHeader
        title="Classification logs"
        subtitle="Per-row audit trail — why each business was included or excluded."
        icon={<FileText className="h-6 w-6 text-primary" />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Stat label="Total decisions" value={total.toLocaleString()} />
        <Stat label="Included" value={included.toLocaleString()} hint={`${inclRate}% of total`} variant="success" icon={<CheckCircle className="h-3 w-3" />} />
        <Stat label="Excluded" value={excluded.toLocaleString()} hint={`${100 - inclRate}% of total`} variant="danger" icon={<XCircle className="h-3 w-3" />} />
        <Stat label="Filtered" value={(query.data?.total ?? 0).toLocaleString()} hint={`${activeFilterCount} filter${activeFilterCount === 1 ? "" : "s"}`} variant="info" />
      </div>

      <div className="rounded-lg border bg-card p-3 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); resetPage(); }}
              placeholder="Search name, reason, classifier text…"
              className="w-full rounded-md border bg-background pl-8 pr-8 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            {search && (
              <button
                onClick={() => { setSearch(""); resetPage(); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <FilterChip
            label="Decision"
            options={facets.data?.decisions ?? []}
            selected={decisionFilter}
            onChange={(v) => { setDecisionFilter(v); resetPage(); }}
          />
          <FilterChip
            label="Tier"
            options={facets.data?.tiers ?? []}
            selected={tierFilter}
            onChange={(v) => { setTierFilter(v); resetPage(); }}
          />
          {activeFilterCount > 0 && (
            <button
              onClick={clearAll}
              className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 ml-1"
            >
              <X className="h-3 w-3" /> Clear all
            </button>
          )}
        </div>
      </div>

      <DataTable
        data={query.data?.rows ?? []}
        columns={columns}
        total={query.data?.total ?? 0}
        pageIndex={pageIndex}
        pageSize={pageSize}
        sorting={sorting}
        onSortingChange={(updater) => {
          setSorting(typeof updater === "function" ? updater(sorting) : updater);
          resetPage();
        }}
        onPageChange={setPageIndex}
        onPageSizeChange={(n) => { setPageSize(n); setPageIndex(0); }}
        onRowClick={setSelected}
        isLoading={query.isLoading}
        isFetching={query.isFetching}
        rowKey={(r) => r.id}
        emptyMessage="No classification decisions match these filters."
      />

      <LogDrawer log={selected} open={!!selected} onClose={() => setSelected(null)} />
    </div>
  );
}
