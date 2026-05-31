import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { Tags, Plus, Pencil, Trash2, Search, X, Loader2, AlertCircle, Power } from "lucide-react";
import { api, ApiError, type Keyword } from "@/lib/api";
import { DataTable } from "@/components/grid/DataTable";
import { KeywordDrawer } from "@/components/drawer/KeywordDrawer";
import { Badge, tierVariant, PageHeader } from "@/components/ui-bits";

const TIERS = [
  "TIER_1_DRYWALL",
  "TIER_1_GC",
  "TIER_2_PAINTER",
  "TIER_2_REMODELER",
  "TIER_3_HANDYMAN",
  "EXCLUDE_HARD",
  "EXCLUDE_SOLO",
];

export default function Keywords() {
  const qc = useQueryClient();
  const [tier, setTier] = useState(TIERS[0]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Keyword | null>(null);
  const [editing, setEditing] = useState<Keyword | null>(null);
  const [creating, setCreating] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Keyword | null>(null);

  const facets = useQuery({
    queryKey: ["keyword-facets"],
    queryFn: () => api.keywordFacets(),
  });

  const query = useQuery({
    queryKey: ["keywords", tier, search],
    queryFn: () => api.listKeywords({ tier, search: search.trim() || undefined }),
    placeholderData: keepPreviousData,
  });

  function showErr(e: unknown) {
    if (e instanceof ApiError) setGlobalError(e.detail?.detail || e.detail?.error || `Error ${e.status}`);
    else setGlobalError((e as Error).message);
    setTimeout(() => setGlobalError(null), 4000);
  }

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["keywords"] });
    qc.invalidateQueries({ queryKey: ["keyword-facets"] });
  }

  const toggleActive = useMutation({
    mutationFn: (k: Keyword) => api.updateKeyword(k.id, { active: !k.active }),
    onSuccess: invalidate,
    onError: showErr,
  });

  const deleteOne = useMutation({
    mutationFn: (k: Keyword) => api.deleteKeyword(k.id),
    onSuccess: () => { setConfirmDelete(null); invalidate(); },
    onError: (e) => { setConfirmDelete(null); showErr(e); },
  });

  // Client-side sort/pagination — keyword lists are tiny per tier.
  const [sorting, setSorting] = useState<SortingState>([{ id: "keyword", desc: false }]);
  const [pageIndex, setPageIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const sorted = useMemo(() => {
    const data = [...(query.data ?? [])];
    if (sorting[0]) {
      const { id, desc } = sorting[0];
      data.sort((a: any, b: any) => {
        const av = a[id], bv = b[id];
        if (av == null) return 1;
        if (bv == null) return -1;
        if (av < bv) return desc ? 1 : -1;
        if (av > bv) return desc ? -1 : 1;
        return 0;
      });
    }
    return data;
  }, [query.data, sorting]);

  const total = sorted.length;
  const pageRows = sorted.slice(pageIndex * pageSize, (pageIndex + 1) * pageSize);

  const columns = useMemo<ColumnDef<Keyword, any>[]>(() => [
    { id: "keyword", accessorKey: "keyword", header: "Keyword",
      cell: ({ getValue }) => <code className="font-mono text-sm">{getValue() as string}</code>,
    },
    { id: "active", accessorKey: "active", header: "Active",
      cell: ({ row }) => (
        <button
          onClick={(e) => { e.stopPropagation(); toggleActive.mutate(row.original); }}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium transition ${
            row.original.active
              ? "bg-emerald-100 text-emerald-800 hover:bg-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300"
              : "bg-muted text-muted-foreground hover:bg-secondary"
          }`}
        >
          <Power className="h-3 w-3" />
          {row.original.active ? "Active" : "Inactive"}
        </button>
      ),
    },
    { id: "notes", accessorKey: "notes", header: "Notes",
      cell: ({ getValue }) => <span className="text-xs text-muted-foreground">{(getValue() as string) || "—"}</span>,
    },
    { id: "created_at", accessorKey: "created_at", header: "Created",
      cell: ({ getValue }) => <span className="text-xs text-muted-foreground">{new Date(getValue() as string).toLocaleDateString()}</span>,
    },
    { id: "actions", enableSorting: false, header: "",
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100">
          <button
            onClick={(e) => { e.stopPropagation(); setEditing(row.original); }}
            className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary text-muted-foreground"
            title="Edit"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setConfirmDelete(row.original); }}
            className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-destructive/10 text-destructive"
            title="Delete"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ),
    },
  ], [toggleActive]);

  function facetCount(t: string) {
    return facets.data?.find((f) => f.value === t)?.n ?? 0;
  }

  return (
    <div className="p-6 max-w-[1400px] mx-auto">
      <PageHeader
        title="Keywords"
        subtitle="Tier classifier dictionary. All edits are audit-logged."
        icon={<Tags className="h-6 w-6 text-primary" />}
        actions={
          <button
            onClick={() => setCreating(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-medium hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" /> Add keyword
          </button>
        }
      />

      {globalError && (
        <div className="mb-3 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{globalError}</span>
        </div>
      )}

      {/* Tier tabs */}
      <div className="flex flex-wrap gap-1 mb-4 border-b">
        {TIERS.map((t) => {
          const n = facetCount(t);
          return (
            <button
              key={t}
              onClick={() => { setTier(t); setPageIndex(0); }}
              className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition ${
                tier === t
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <span className="font-mono">{t}</span>
              {n > 0 && <span className="ml-1.5 text-muted-foreground tabular-nums">({n})</span>}
            </button>
          );
        })}
      </div>

      {/* Active tier header + search */}
      <div className="flex items-center justify-between mb-3 gap-2">
        <Badge variant={tierVariant(tier)} className="text-sm py-1 px-2.5">{tier}</Badge>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPageIndex(0); }}
            placeholder="Search keyword or notes…"
            className="rounded-md border bg-background pl-8 pr-3 py-1.5 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
      </div>

      <div className="group">
        <DataTable
          data={pageRows}
          columns={columns}
          total={total}
          pageIndex={pageIndex}
          pageSize={pageSize}
          sorting={sorting}
          onSortingChange={(u) => setSorting(typeof u === "function" ? u(sorting) : u)}
          onPageChange={setPageIndex}
          onPageSizeChange={(n) => { setPageSize(n); setPageIndex(0); }}
          onRowClick={setSelected}
          isLoading={query.isLoading}
          isFetching={query.isFetching}
          rowKey={(r) => r.id}
          emptyMessage={search ? "No keywords match your search." : "No keywords in this tier yet."}
        />
      </div>

      <KeywordDrawer keyword={selected} open={!!selected} onClose={() => setSelected(null)} />

      {(creating || editing) && (
        <KeywordDialog
          tier={tier}
          existing={editing}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { setCreating(false); setEditing(null); invalidate(); }}
          onError={showErr}
        />
      )}

      {confirmDelete && (
        <ConfirmDialog
          message={<>Delete keyword <code className="font-mono">{confirmDelete.keyword}</code>?</>}
          confirmLabel={deleteOne.isPending ? "Deleting…" : "Yes, delete"}
          danger
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => deleteOne.mutate(confirmDelete)}
        />
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
function KeywordDialog({
  tier,
  existing,
  onClose,
  onSaved,
  onError,
}: {
  tier: string;
  existing: Keyword | null;
  onClose: () => void;
  onSaved: () => void;
  onError: (e: unknown) => void;
}) {
  const [text, setText] = useState(existing?.keyword ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [active, setActive] = useState(existing?.active ?? true);
  const [reason, setReason] = useState("");
  const [selectedTier, setSelectedTier] = useState(existing?.tier ?? tier);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => {
      if (existing) {
        return api.updateKeyword(existing.id, {
          keyword: text.toLowerCase().trim(),
          notes: notes || undefined,
          active,
          reason: reason || undefined,
        });
      }
      return api.createKeyword({
        tier: selectedTier,
        keyword: text.toLowerCase().trim(),
        notes: notes || undefined,
        reason: reason || undefined,
      });
    },
    onSuccess: onSaved,
    onError: (e) => {
      // 409 (duplicate keyword) and other failures must surface inside the
      // dialog — the parent's global banner is hidden behind this modal's backdrop.
      if (e instanceof ApiError) {
        setError(
          e.status === 409
            ? e.detail?.detail || "This keyword already exists for the selected tier."
            : e.detail?.detail || e.detail?.error || `Error ${e.status}`,
        );
      } else {
        setError((e as Error).message);
      }
      onError(e);
    },
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-semibold mb-1">{existing ? "Edit keyword" : "Add keyword"}</h2>
        <p className="text-xs text-muted-foreground mb-4">All edits are written to <code>keyword_changes</code>.</p>

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="space-y-3">
          {!existing && (
            <div>
              <label className="text-sm font-medium block mb-1">Tier</label>
              <select
                value={selectedTier}
                onChange={(e) => { setSelectedTier(e.target.value); setError(null); }}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              >
                {TIERS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="text-sm font-medium block mb-1">Keyword</label>
            <input
              autoFocus
              value={text}
              onChange={(e) => { setText(e.target.value); setError(null); }}
              placeholder="e.g. sheetrock"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <p className="text-xs text-muted-foreground mt-1">Stored lowercase.</p>
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">Notes</label>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="optional"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          {existing && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="rounded" />
              Active
            </label>
          )}
          <div>
            <label className="text-sm font-medium block mb-1">Reason</label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="why this change (audit log)"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button onClick={onClose} className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary">Cancel</button>
          <button
            onClick={() => save.mutate()}
            disabled={!text.trim() || save.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
          >
            {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {existing ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ConfirmDialog({
  message,
  confirmLabel = "Confirm",
  danger,
  onCancel,
  onConfirm,
}: {
  message: React.ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4" onClick={onCancel}>
      <div className="w-full max-w-sm rounded-xl border bg-card p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <AlertCircle className={danger ? "h-5 w-5 text-destructive shrink-0" : "h-5 w-5 text-amber-500 shrink-0"} />
          <div className="text-sm">{message}</div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="rounded-md border px-4 py-1.5 text-sm hover:bg-secondary">Cancel</button>
          <button
            onClick={onConfirm}
            className={`rounded-md px-4 py-1.5 text-sm font-medium ${
              danger
                ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
                : "bg-primary text-primary-foreground hover:bg-primary/90"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
