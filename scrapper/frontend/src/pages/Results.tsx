import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import type { ColumnDef, SortingState, VisibilityState } from "@tanstack/react-table";
import {
  Users, Search, X, Star, Download, Loader2, ExternalLink,
  SlidersHorizontal, ChevronDown, Check, FileSpreadsheet,
  Facebook, Instagram, Linkedin, Twitter, Youtube, Link2,
} from "lucide-react";
import { api, type Contractor, type ContractorQuery } from "@/lib/api";
import { DataTable, sortingToParams } from "@/components/grid/DataTable";
import { ContractorDrawer } from "@/components/drawer/ContractorDrawer";
import { Badge, tierVariant, licenseVariant, PageHeader, Stat, EmptyValue } from "@/components/ui-bits";
import { cn } from "@/lib/utils";

// Column id → label, in display order. Drives both the table columns and the
// "Columns" show/hide menu. Every output-schema field is represented.
const COLUMN_LABELS: { id: string; label: string }[] = [
  { id: "business_name", label: "Business" },
  { id: "change_status", label: "Change" },
  { id: "city", label: "City" },
  { id: "zip_code", label: "Zip" },
  { id: "address", label: "Address" },
  { id: "tier", label: "Tier" },
  { id: "specialty_keywords", label: "Tier keywords" },
  { id: "google_categories", label: "Categories" },
  { id: "services_listed", label: "Services" },
  { id: "phone", label: "Phone" },
  { id: "email", label: "Email" },
  { id: "website", label: "Website" },
  { id: "owner_name", label: "Owner" },
  { id: "license_status", label: "License" },
  { id: "license_numbers", label: "Lic #" },
  { id: "license_categories", label: "Lic categories" },
  { id: "google_rating", label: "Rating" },
  { id: "google_review_count", label: "Reviews" },
  { id: "bbb_rating", label: "BBB" },
  { id: "bbb_accredited", label: "BBB accredited" },
  { id: "years_in_business", label: "Years" },
  { id: "social_profiles", label: "Social" },
  { id: "sources", label: "Sources" },
  { id: "place_ids", label: "Place IDs" },
  { id: "scraped_at", label: "Scraped" },
  { id: "job_id", label: "Job" },
];

export default function Results() {
  const [search, setSearch] = useState("");
  // enum facets (single-select native dropdowns, sent as a one-element ANY filter)
  const [cityFilter, setCityFilter] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [licenseFilter, setLicenseFilter] = useState("");
  // presence toggles
  const [hasPhone, setHasPhone] = useState<boolean | undefined>(undefined);
  const [hasEmail, setHasEmail] = useState<boolean | undefined>(undefined);
  const [hasWebsite, setHasWebsite] = useState<boolean | undefined>(undefined);
  const [bbbAccredited, setBbbAccredited] = useState<boolean | undefined>(undefined);
  // free-text "contains" filters, keyed by column id
  const [textFilters, setTextFilters] = useState<Record<string, string>>({});
  // numeric minimums, keyed by param name
  const [minFilters, setMinFilters] = useState<Record<string, string>>({});

  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({});

  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [sorting, setSorting] = useState<SortingState>([{ id: "id", desc: true }]);

  const [selected, setSelected] = useState<Contractor | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  const sortParams = sortingToParams(sorting);

  // Debounce the typed filters so we don't fire a request per keystroke.
  const debSearch = useDebounced(search);
  const debText = useDebounced(textFilters);
  const debMin = useDebounced(minFilters);

  const facets = useQuery({
    queryKey: ["contractor-facets"],
    queryFn: () => api.contractorFacets(),
  });

  // ── Result-set source: a per-run dynamic sheet, or the cumulative master ──
  // "" = master (contractors tab); otherwise a job_id whose run sheet we view.
  const sheets = useQuery({ queryKey: ["result-sheets"], queryFn: () => api.listResultSheets() });
  const [sheetJobId, setSheetJobId] = useState<string>("");
  const sheetInit = useRef(false);
  useEffect(() => {
    // Default to the most recent run's sheet on first load (user can switch).
    if (!sheetInit.current && sheets.data) {
      sheetInit.current = true;
      if (sheets.data.length) setSheetJobId(sheets.data[0].job_id);
    }
  }, [sheets.data]);
  const usingSheet = !!sheetJobId;
  const selectedSheet = sheets.data?.find((s) => s.job_id === sheetJobId) ?? null;

  function resetPage() {
    setPageIndex((p) => (p !== 0 ? 0 : p));
  }
  function setText(key: string, v: string) {
    setTextFilters((prev) => ({ ...prev, [key]: v }));
    resetPage();
  }
  function setMin(key: string, v: string) {
    setMinFilters((prev) => ({ ...prev, [key]: v }));
    resetPage();
  }

  const txt = (k: string) => (debText[k]?.trim() ? debText[k].trim() : undefined);
  const num = (k: string) => {
    const raw = debMin[k];
    if (raw == null || String(raw).trim() === "") return undefined;
    const n = Number(raw);
    return Number.isNaN(n) ? undefined : n;
  };

  const apiParams: ContractorQuery = {
    search: debSearch.trim() || undefined,
    city: cityFilter ? [cityFilter] : undefined,
    tier: tierFilter ? [tierFilter] : undefined,
    license_status: licenseFilter ? [licenseFilter] : undefined,
    has_phone: hasPhone,
    has_email: hasEmail,
    has_website: hasWebsite,
    bbb_accredited: bbbAccredited,
    business_name: txt("business_name"),
    zip_code: txt("zip_code"),
    address: txt("address"),
    owner_name: txt("owner_name"),
    bbb_rating: txt("bbb_rating"),
    specialty_keywords: txt("specialty_keywords"),
    google_categories: txt("google_categories"),
    services_listed: txt("services_listed"),
    license_numbers: txt("license_numbers"),
    license_categories: txt("license_categories"),
    sources: txt("sources"),
    place_ids: txt("place_ids"),
    min_rating: num("min_rating"),
    min_review_count: num("min_review_count"),
    min_years: num("min_years"),
    sort_by: sortParams.sort_by,
    sort_dir: sortParams.sort_dir,
    limit: pageSize,
    offset: pageIndex * pageSize,
  };

  const query = useQuery({
    queryKey: ["contractors", sheetJobId, apiParams],
    queryFn: () =>
      usingSheet ? api.listSheetContractors(sheetJobId, apiParams) : api.listContractors(apiParams),
    placeholderData: keepPreviousData,
  });

  const activeFilterCount =
    (cityFilter ? 1 : 0) + (tierFilter ? 1 : 0) + (licenseFilter ? 1 : 0) +
    (hasPhone !== undefined ? 1 : 0) + (hasEmail !== undefined ? 1 : 0) +
    (hasWebsite !== undefined ? 1 : 0) + (bbbAccredited !== undefined ? 1 : 0) +
    Object.values(textFilters).filter((v) => v.trim()).length +
    Object.values(minFilters).filter((v) => String(v).trim()).length +
    (search.trim() ? 1 : 0);

  function clearAll() {
    setSearch(""); setCityFilter(""); setTierFilter(""); setLicenseFilter("");
    setHasPhone(undefined); setHasEmail(undefined); setHasWebsite(undefined); setBbbAccredited(undefined);
    setTextFilters({}); setMinFilters({});
    setPageIndex(0);
  }

  async function handleExport() {
    if (isExporting) return;
    setIsExporting(true);
    try {
      const { limit: _l, offset: _o, ...exportParams } = apiParams;
      void _l; void _o;
      await api.exportContractors(exportParams);
    } catch (err) {
      console.error("Export failed", err);
      alert("Export failed — see console for details.");
    } finally {
      setIsExporting(false);
    }
  }

  const exportCount = query.data?.total ?? 0;
  const canExport = exportCount > 0 && !isExporting;

  // ── Columns: one per output-schema field ──
  const columns = useMemo<ColumnDef<Contractor, any>[]>(() => [
    {
      id: "business_name", accessorKey: "business_name", header: "Business",
      cell: ({ getValue }) => <div className="font-medium min-w-[170px]">{(getValue() as string) || <EmptyValue />}</div>,
    },
    {
      id: "city", accessorKey: "city", header: "City",
      cell: ({ getValue }) => <span className="text-sm whitespace-nowrap">{(getValue() as string) ?? <EmptyValue />}</span>,
    },
    {
      id: "zip_code", accessorKey: "zip_code", header: "Zip",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="font-mono text-xs">{v}</span> : <EmptyValue />; },
    },
    {
      id: "address", accessorKey: "address", header: "Address",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="text-xs text-muted-foreground block max-w-[220px] truncate" title={v}>{v}</span> : <EmptyValue />; },
    },
    {
      id: "tier", accessorKey: "tier", header: "Tier",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <Badge variant={tierVariant(v)}>{v}</Badge> : <EmptyValue />; },
    },
    {
      id: "change_status", accessorKey: "change_status", header: "Change", enableSorting: false,
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        if (!v) return <EmptyValue />;
        const variant = v === "new" ? "success" : v === "updated" ? "warning" : "muted";
        return <Badge variant={variant}>{v}</Badge>;
      },
    },
    {
      id: "specialty_keywords", header: "Tier keywords", enableSorting: false,
      cell: ({ row }) => <ListCell values={row.original.specialty_keywords} variant="success" />,
    },
    {
      id: "google_categories", header: "Categories", enableSorting: false,
      cell: ({ row }) => <ListCell values={row.original.google_categories} variant="info" />,
    },
    {
      id: "services_listed", header: "Services", enableSorting: false,
      cell: ({ row }) => <ListCell values={row.original.services_listed} variant="muted" />,
    },
    {
      id: "phone", accessorKey: "phone", header: "Phone",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="font-mono text-xs whitespace-nowrap">{v}</span> : <EmptyValue />; },
    },
    {
      id: "email", accessorKey: "email", header: "Email",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="text-xs truncate max-w-[180px] inline-block" title={v}>{v}</span> : <EmptyValue />; },
    },
    {
      id: "website", accessorKey: "website", header: "Website",
      cell: ({ getValue }) => {
        const v = getValue() as string | null;
        if (!v) return <EmptyValue />;
        const label = v.replace(/^https?:\/\//, "").replace(/\/$/, "");
        return (
          <a href={v} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
             className="text-xs text-primary hover:underline inline-flex items-center gap-1 max-w-[180px]">
            <span className="truncate">{label}</span>
            <ExternalLink className="h-3 w-3 shrink-0" />
          </a>
        );
      },
    },
    {
      id: "owner_name", accessorKey: "owner_name", header: "Owner",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="text-xs whitespace-nowrap">{v}</span> : <EmptyValue />; },
    },
    {
      id: "license_status", accessorKey: "license_status", header: "License",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <Badge variant={licenseVariant(v)}>{v}</Badge> : <EmptyValue />; },
    },
    {
      id: "license_numbers", header: "Lic #", enableSorting: false,
      cell: ({ row }) => {
        const ns = row.original.license_numbers;
        if (!ns?.length) return <EmptyValue />;
        return (
          <div className="flex flex-wrap gap-1 max-w-[150px]">
            {ns.slice(0, 2).map((n) => <code key={n} className="rounded bg-muted px-1 py-0.5 text-[10px]">{n}</code>)}
            {ns.length > 2 && <span className="text-[10px] text-muted-foreground self-center">+{ns.length - 2}</span>}
          </div>
        );
      },
    },
    {
      id: "license_categories", header: "Lic categories", enableSorting: false,
      cell: ({ row }) => <ListCell values={row.original.license_categories} variant="muted" />,
    },
    {
      id: "google_rating", accessorKey: "google_rating", header: "Rating",
      cell: ({ getValue }) => {
        const r = getValue() as number | null;
        if (r == null) return <EmptyValue />;
        return (
          <span className="inline-flex items-center gap-1 text-xs">
            <Star className="h-3 w-3 fill-amber-400 text-amber-400" />
            <span className="font-medium">{r}</span>
          </span>
        );
      },
    },
    {
      id: "google_review_count", accessorKey: "google_review_count", header: "Reviews",
      cell: ({ getValue }) => { const v = getValue() as number | null; return v != null ? <span className="text-xs tabular-nums">{v.toLocaleString()}</span> : <EmptyValue />; },
    },
    {
      id: "bbb_rating", accessorKey: "bbb_rating", header: "BBB",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <Badge variant="muted">{v}</Badge> : <EmptyValue />; },
    },
    {
      id: "bbb_accredited", accessorKey: "bbb_accredited", header: "BBB accredited",
      cell: ({ getValue }) => {
        const v = getValue() as boolean | null;
        if (v == null) return <EmptyValue />;
        return <Badge variant={v ? "success" : "muted"}>{v ? "yes" : "no"}</Badge>;
      },
    },
    {
      id: "years_in_business", accessorKey: "years_in_business", header: "Years",
      cell: ({ getValue }) => { const v = getValue() as number | null; return v != null ? <span className="text-xs tabular-nums">{v}</span> : <EmptyValue />; },
    },
    {
      id: "social_profiles", header: "Social", enableSorting: false,
      cell: ({ row }) => <SocialCell profiles={row.original.social_profiles} />,
    },
    {
      id: "sources", header: "Sources", enableSorting: false,
      cell: ({ row }) => <ListCell values={row.original.sources} variant="muted" max={3} />,
    },
    {
      id: "place_ids", header: "Place IDs", enableSorting: false,
      cell: ({ row }) => {
        const ids = row.original.place_ids;
        if (!ids?.length) return <EmptyValue />;
        return (
          <div className="flex flex-col gap-0.5 max-w-[150px]">
            {ids.slice(0, 2).map((p) => <code key={p} className="text-[10px] truncate" title={p}>{p}</code>)}
            {ids.length > 2 && <span className="text-[10px] text-muted-foreground">+{ids.length - 2}</span>}
          </div>
        );
      },
    },
    {
      id: "scraped_at", accessorKey: "scraped_at", header: "Scraped",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <span className="text-xs whitespace-nowrap">{new Date(v).toLocaleDateString()}</span> : <EmptyValue />; },
    },
    {
      id: "job_id", accessorKey: "job_id", header: "Job",
      cell: ({ getValue }) => { const v = getValue() as string | null; return v ? <code className="text-[10px] text-muted-foreground" title={v}>{v.slice(0, 8)}…</code> : <EmptyValue />; },
    },
  ], []);

  // ── Per-column header filter controls, keyed by column id ──
  const columnFilters: Record<string, React.ReactNode> = {
    business_name: <HeaderText value={textFilters.business_name ?? ""} onChange={(v) => setText("business_name", v)} placeholder="name…" />,
    city: <HeaderSelect value={cityFilter} onChange={(v) => { setCityFilter(v); resetPage(); }} options={facets.data?.cities ?? []} />,
    zip_code: <HeaderText value={textFilters.zip_code ?? ""} onChange={(v) => setText("zip_code", v)} placeholder="zip…" />,
    address: <HeaderText value={textFilters.address ?? ""} onChange={(v) => setText("address", v)} />,
    tier: <HeaderSelect value={tierFilter} onChange={(v) => { setTierFilter(v); resetPage(); }} options={facets.data?.tiers ?? []} />,
    specialty_keywords: <HeaderText value={textFilters.specialty_keywords ?? ""} onChange={(v) => setText("specialty_keywords", v)} />,
    google_categories: <HeaderText value={textFilters.google_categories ?? ""} onChange={(v) => setText("google_categories", v)} />,
    services_listed: <HeaderText value={textFilters.services_listed ?? ""} onChange={(v) => setText("services_listed", v)} />,
    phone: <HeaderBool value={hasPhone} onChange={(v) => { setHasPhone(v); resetPage(); }} />,
    email: <HeaderBool value={hasEmail} onChange={(v) => { setHasEmail(v); resetPage(); }} />,
    website: <HeaderBool value={hasWebsite} onChange={(v) => { setHasWebsite(v); resetPage(); }} />,
    owner_name: <HeaderText value={textFilters.owner_name ?? ""} onChange={(v) => setText("owner_name", v)} />,
    license_status: <HeaderSelect value={licenseFilter} onChange={(v) => { setLicenseFilter(v); resetPage(); }} options={facets.data?.license_statuses ?? []} />,
    license_numbers: <HeaderText value={textFilters.license_numbers ?? ""} onChange={(v) => setText("license_numbers", v)} />,
    license_categories: <HeaderText value={textFilters.license_categories ?? ""} onChange={(v) => setText("license_categories", v)} />,
    google_rating: <HeaderMin value={minFilters.min_rating ?? ""} onChange={(v) => setMin("min_rating", v)} />,
    google_review_count: <HeaderMin value={minFilters.min_review_count ?? ""} onChange={(v) => setMin("min_review_count", v)} />,
    bbb_rating: <HeaderText value={textFilters.bbb_rating ?? ""} onChange={(v) => setText("bbb_rating", v)} placeholder="A+…" />,
    bbb_accredited: <HeaderBool value={bbbAccredited} onChange={(v) => { setBbbAccredited(v); resetPage(); }} />,
    years_in_business: <HeaderMin value={minFilters.min_years ?? ""} onChange={(v) => setMin("min_years", v)} />,
    sources: <HeaderText value={textFilters.sources ?? ""} onChange={(v) => setText("sources", v)} />,
    place_ids: <HeaderText value={textFilters.place_ids ?? ""} onChange={(v) => setText("place_ids", v)} />,
  };

  return (
    <div className="p-6">
      <PageHeader
        title="Results"
        subtitle="Final scraped contractor data — every field shown, filter per column, click any row for full details."
        icon={<Users className="h-6 w-6 text-primary" />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Stat label="Total" value={(facets.data?.total ?? 0).toLocaleString()} hint="all contractors" />
        <Stat label="Filtered" value={(query.data?.total ?? 0).toLocaleString()} hint={`${activeFilterCount} filter${activeFilterCount === 1 ? "" : "s"}`} variant="info" />
        <Stat label="Cities" value={(facets.data?.cities?.length ?? 0).toLocaleString()} hint="distinct" />
        <Stat label="Tiers" value={(facets.data?.tiers?.length ?? 0).toLocaleString()} hint="distinct" />
      </div>

      <div className="rounded-lg border bg-card p-3 mb-4">
        {/* Result-set selector: which run's sheet to view (or the cumulative master) */}
        <div className="flex flex-wrap items-center gap-2 mb-2 pb-2 border-b">
          <FileSpreadsheet className="h-4 w-4 text-primary shrink-0" />
          <span className="text-xs font-medium text-muted-foreground">Result set:</span>
          <select
            value={sheetJobId}
            onChange={(e) => { setSheetJobId(e.target.value); resetPage(); }}
            className="rounded-md border bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary max-w-[340px]"
          >
            <option value="">Master — all runs (cumulative)</option>
            {sheets.data?.map((s) => (
              <option key={s.job_id} value={s.job_id}>
                {s.name || `Run ${s.job_id.slice(0, 8)}`}
                {s.status && s.status !== "completed" ? ` · ${s.status}` : ""}
              </option>
            ))}
          </select>
          {usingSheet && selectedSheet?.url && (
            <a
              href={selectedSheet.url} target="_blank" rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              Open in Google Sheets <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {usingSheet && (
            <span className="text-[11px] text-muted-foreground">
              showing this run's snapshot · <b>new/updated/unchanged</b> tagged
            </span>
          )}
        </div>

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

          <ColumnsMenu columns={COLUMN_LABELS} visibility={columnVisibility} onChange={setColumnVisibility} />

          {activeFilterCount > 0 && (
            <button
              onClick={clearAll}
              className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1 ml-1"
            >
              <X className="h-3 w-3" /> Clear all
            </button>
          )}

          {!usingSheet && (
            <button
              onClick={handleExport}
              disabled={!canExport}
              className="ml-auto inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              {isExporting ? "Exporting…" : `Download CSV${exportCount > 0 ? ` (${exportCount.toLocaleString()})` : ""}`}
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
        columnVisibility={columnVisibility}
        onColumnVisibilityChange={setColumnVisibility}
        columnFilters={columnFilters}
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

// ── Hooks ──

/** Returns `value` after it has stayed unchanged for `ms`. */
function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

// ── Header filter controls (module-level so the inputs keep focus across renders) ──

function HeaderText({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "filter…"}
        className="w-full min-w-[90px] rounded border bg-background px-2 py-1 pr-5 text-xs font-normal normal-case tracking-normal focus:outline-none focus:ring-1 focus:ring-primary"
      />
      {value && (
        <button type="button" onClick={() => onChange("")} className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

function HeaderMin({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="min"
      className="w-full min-w-[60px] rounded border bg-background px-2 py-1 text-xs font-normal normal-case focus:outline-none focus:ring-1 focus:ring-primary"
    />
  );
}

function HeaderBool({ value, onChange }: { value: boolean | undefined; onChange: (v: boolean | undefined) => void }) {
  const next = () => onChange(value === undefined ? true : value ? false : undefined);
  const label = value === undefined ? "any" : value ? "yes" : "no";
  return (
    <button
      type="button"
      onClick={next}
      className={cn(
        "w-full rounded border px-2 py-1 text-xs font-normal normal-case transition",
        value !== undefined ? "bg-primary/10 border-primary/30 text-primary" : "bg-background hover:bg-secondary",
      )}
    >
      {label}
    </button>
  );
}

function HeaderSelect({ value, onChange, options }: { value: string; onChange: (v: string) => void; options: { value: string; n?: number }[] }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "w-full min-w-[110px] rounded border px-1.5 py-1 text-xs font-normal normal-case focus:outline-none focus:ring-1 focus:ring-primary",
        value ? "bg-primary/10 border-primary/30 text-primary" : "bg-background",
      )}
    >
      <option value="">All</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.value}{o.n != null ? ` (${o.n})` : ""}</option>
      ))}
    </select>
  );
}

// ── Columns show/hide menu ──

function ColumnsMenu({
  columns,
  visibility,
  onChange,
}: {
  columns: { id: string; label: string }[];
  visibility: VisibilityState;
  onChange: (v: VisibilityState) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const isVisible = (id: string) => visibility[id] !== false;
  const shownCount = columns.filter((c) => isVisible(c.id)).length;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 rounded-md border bg-card px-3 py-1.5 text-xs font-medium hover:bg-secondary"
      >
        <SlidersHorizontal className="h-3.5 w-3.5" /> Columns
        <span className="ml-0.5 rounded-full bg-secondary px-1.5 text-[10px] tabular-nums">{shownCount}/{columns.length}</span>
        <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-1 w-56 rounded-md border bg-popover text-popover-foreground shadow-lg overflow-hidden">
          <div className="flex items-center justify-between border-b px-3 py-1.5 text-xs">
            <button type="button" className="hover:text-primary" onClick={() => onChange(Object.fromEntries(columns.map((c) => [c.id, true])))}>Show all</button>
            <button type="button" className="hover:text-primary" onClick={() => onChange(Object.fromEntries(columns.map((c) => [c.id, false])))}>Hide all</button>
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            {columns.map((c) => {
              const vis = isVisible(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onChange({ ...visibility, [c.id]: !vis })}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-xs hover:bg-secondary text-left"
                >
                  <span className={cn("h-4 w-4 rounded border inline-flex items-center justify-center", vis ? "bg-primary border-primary text-primary-foreground" : "bg-background")}>
                    {vis && <Check className="h-3 w-3" />}
                  </span>
                  <span className="flex-1 truncate">{c.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Cell helpers ──

function ListCell({ values, variant = "muted", max = 2 }: { values?: string[] | null; variant?: "default" | "success" | "danger" | "warning" | "info" | "muted"; max?: number }) {
  if (!values || values.length === 0) return <EmptyValue />;
  return (
    <div className="flex flex-wrap gap-1 max-w-[200px]">
      {values.slice(0, max).map((v) => <Badge key={v} variant={variant}>{v}</Badge>)}
      {values.length > max && <span className="text-[10px] text-muted-foreground self-center">+{values.length - max}</span>}
    </div>
  );
}

function SocialCell({ profiles }: { profiles?: Record<string, string> | null }) {
  const entries = profiles ? Object.entries(profiles).filter(([, url]) => url) : [];
  if (entries.length === 0) return <EmptyValue />;
  return (
    <div className="flex items-center gap-1.5">
      {entries.map(([platform, url]) => (
        <a
          key={platform}
          href={url}
          target="_blank"
          rel="noreferrer"
          title={platform}
          onClick={(e) => e.stopPropagation()}
          className="text-muted-foreground hover:text-primary"
        >
          {socialIcon(platform)}
        </a>
      ))}
    </div>
  );
}

function socialIcon(platform: string) {
  const p = platform.toLowerCase();
  const cls = "h-3.5 w-3.5";
  if (p.includes("facebook")) return <Facebook className={cls} />;
  if (p.includes("instagram")) return <Instagram className={cls} />;
  if (p.includes("linkedin")) return <Linkedin className={cls} />;
  if (p.includes("twitter") || p === "x") return <Twitter className={cls} />;
  if (p.includes("youtube")) return <Youtube className={cls} />;
  return <Link2 className={cls} />;
}
