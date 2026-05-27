import { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Users, Search, X, Star, Phone, Mail, Download, Loader2 } from "lucide-react";
import { api, type Contractor } from "@/lib/api";
import { DataTable, sortingToParams } from "@/components/grid/DataTable";
import { FilterChip, BoolChip } from "@/components/grid/FilterChip";
import { ContractorDrawer } from "@/components/drawer/ContractorDrawer";
import { Badge, tierVariant, licenseVariant, PageHeader, Stat, EmptyValue } from "@/components/ui-bits";

export default function Results() {
  const [search, setSearch] = useState("");
  const [cityFilter, setCityFilter] = useState<string[]>([]);
  const [tierFilter, setTierFilter] = useState<string[]>([]);
  const [licenseFilter, setLicenseFilter] = useState<string[]>([]);
  const [hasEmail, setHasEmail] = useState<boolean | undefined>(undefined);
  const [hasPhone, setHasPhone] = useState<boolean | undefined>(undefined);
  const [hasWebsite, setHasWebsite] = useState<boolean | undefined>(undefined);

  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([{ id: "id", desc: true }]);

  const [selected, setSelected] = useState<Contractor | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const sortParams = sortingToParams(sorting);

  const facets = useQuery({
    queryKey: ["contractor-facets"],
    queryFn: () => api.contractorFacets(),
  });

  const query = useQuery({
    queryKey: ["contractors", { search, cityFilter, tierFilter, licenseFilter, hasEmail, hasPhone, hasWebsite, sortParams, pageIndex, pageSize }],
    queryFn: () =>
      api.listContractors({
        search: search.trim() || undefined,
        city: cityFilter,
        tier: tierFilter,
        license_status: licenseFilter,
        has_email: hasEmail,
        has_phone: hasPhone,
        has_website: hasWebsite,
        sort_by: sortParams.sort_by,
        sort_dir: sortParams.sort_dir,
        limit: pageSize,
        offset: pageIndex * pageSize,
      }),
    placeholderData: keepPreviousData,
  });

  function resetPage() {
    if (pageIndex !== 0) setPageIndex(0);
  }

  const activeFilterCount =
    cityFilter.length + tierFilter.length + licenseFilter.length +
    (hasEmail !== undefined ? 1 : 0) + (hasPhone !== undefined ? 1 : 0) + (hasWebsite !== undefined ? 1 : 0) +
    (search.trim() ? 1 : 0);

  function clearAll() {
    setSearch(""); setCityFilter([]); setTierFilter([]); setLicenseFilter([]);
    setHasEmail(undefined); setHasPhone(undefined); setHasWebsite(undefined);
    setPageIndex(0);
  }

  async function handleExport() {
    if (isExporting) return;
    setIsExporting(true);
    try {
      await api.exportContractors({
        search: search.trim() || undefined,
        city: cityFilter,
        tier: tierFilter,
        license_status: licenseFilter,
        has_email: hasEmail,
        has_phone: hasPhone,
        has_website: hasWebsite,
        sort_by: sortParams.sort_by,
        sort_dir: sortParams.sort_dir,
      });
    } catch (err) {
      console.error("Export failed", err);
      alert("Export failed — see console for details.");
    } finally {
      setIsExporting(false);
    }
  }

  const exportCount = query.data?.total ?? 0;
  const canExport = exportCount > 0 && !isExporting;

  const columns = useMemo<ColumnDef<Contractor, any>[]>(() => [
    {
      id: "business_name", accessorKey: "business_name", header: "Business",
      cell: ({ row }) => (
        <div className="min-w-[200px]">
          <div className="font-medium">{row.original.business_name}</div>
          {row.original.address && <div className="text-xs text-muted-foreground truncate max-w-[260px]">{row.original.address}</div>}
        </div>
      ),
    },
    { id: "city", accessorKey: "city", header: "City",
      cell: ({ row }) => (
        <div className="text-sm">
          <div>{row.original.city ?? <EmptyValue />}</div>
          {row.original.zip_code && <div className="text-xs text-muted-foreground font-mono">{row.original.zip_code}</div>}
        </div>
      ),
    },
    { id: "tier", accessorKey: "tier", header: "Tier",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <Badge variant={tierVariant(v)}>{v}</Badge> : <EmptyValue />;
      },
    },
    { id: "license_status", accessorKey: "license_status", header: "License",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <Badge variant={licenseVariant(v)}>{v}</Badge> : <EmptyValue />;
      },
    },
    { id: "phone", accessorKey: "phone", header: "Phone",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <span className="font-mono text-xs">{v}</span> : <EmptyValue />;
      },
    },
    { id: "email", accessorKey: "email", header: "Email",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <span className="text-xs truncate max-w-[180px] inline-block">{v}</span> : <EmptyValue />;
      },
    },
    { id: "google_rating", accessorKey: "google_rating", header: "Rating",
      cell: ({ row }) => {
        const r = row.original.google_rating;
        if (r == null) return <EmptyValue />;
        return (
          <span className="inline-flex items-center gap-1 text-xs">
            <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
            <span className="font-medium">{r}</span>
            {row.original.google_review_count != null && (
              <span className="text-muted-foreground">({row.original.google_review_count})</span>
            )}
          </span>
        );
      },
    },
    { id: "bbb_rating", accessorKey: "bbb_rating", header: "BBB",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        return v ? <Badge variant="muted">{v}</Badge> : <EmptyValue />;
      },
    },
  ], []);

  return (
    <div className="p-6">
      <PageHeader
        title="Results"
        subtitle="Final scraped contractor data — filter, sort, click any row for full details."
        icon={<Users className="h-6 w-6 text-primary" />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Stat label="Total" value={(facets.data?.total ?? 0).toLocaleString()} hint="all contractors" />
        <Stat label="Filtered" value={(query.data?.total ?? 0).toLocaleString()} hint={`${activeFilterCount} filter${activeFilterCount === 1 ? "" : "s"}`} variant="info" />
        <Stat
          label="Cities"
          value={(facets.data?.cities?.length ?? 0).toLocaleString()}
          hint="distinct"
          icon={<Phone className="h-3 w-3" />}
        />
        <Stat
          label="Tiers"
          value={(facets.data?.tiers?.length ?? 0).toLocaleString()}
          hint="distinct"
          icon={<Mail className="h-3 w-3" />}
        />
      </div>

      <div className="rounded-lg border bg-card p-3 mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              value={search}
              onChange={(e) => { setSearch(e.target.value); resetPage(); }}
              placeholder="Search name, phone, email, website…"
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
            label="City"
            options={facets.data?.cities ?? []}
            selected={cityFilter}
            onChange={(v) => { setCityFilter(v); resetPage(); }}
          />
          <FilterChip
            label="Tier"
            options={facets.data?.tiers ?? []}
            selected={tierFilter}
            onChange={(v) => { setTierFilter(v); resetPage(); }}
          />
          <FilterChip
            label="License"
            options={facets.data?.license_statuses ?? []}
            selected={licenseFilter}
            onChange={(v) => { setLicenseFilter(v); resetPage(); }}
          />
          <BoolChip label="Phone" value={hasPhone} onChange={(v) => { setHasPhone(v); resetPage(); }} />
          <BoolChip label="Email" value={hasEmail} onChange={(v) => { setHasEmail(v); resetPage(); }} />
          <BoolChip label="Website" value={hasWebsite} onChange={(v) => { setHasWebsite(v); resetPage(); }} />

          {activeFilterCount > 0 && (
            <button
              onClick={clearAll}
              className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 ml-1"
            >
              <X className="h-3 w-3" /> Clear all
            </button>
          )}

          <button
            onClick={handleExport}
            disabled={!canExport}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isExporting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {isExporting
              ? "Exporting…"
              : `Download CSV${exportCount > 0 ? ` (${exportCount.toLocaleString()})` : ""}`}
          </button>
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
        emptyMessage={
          activeFilterCount > 0
            ? "No contractors match these filters."
            : "No contractors yet — kick off a scrape from the Dashboard."
        }
      />

      <ContractorDrawer contractor={selected} open={!!selected} onClose={() => setSelected(null)} />
    </div>
  );
}
