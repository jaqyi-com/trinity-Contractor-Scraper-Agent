import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Network, Plus, Trash2, Pencil, Check, Loader2, AlertCircle } from "lucide-react";
import { api, ApiError, type VendorAlias, type VendorAliasBody } from "@/lib/api";
import { PageHeader, Stat as StatBox, Badge } from "@/components/ui-bits";

const VENDOR_TYPES = ["specialty_distributor", "big_box_retailer", "independent"];

// Vendor alias / subsidiary map — rolls brand/branch names up to ONE canonical
// network so e.g. every GMS local brand (Tucker Materials, Gator Gypsum, Rocky Top
// Materials …) and L&W ↔ ABC Supply merge into a single entity in vendor output.
export default function VendorAliases() {
  const qc = useQueryClient();
  const { data: aliases = [], isLoading, error } = useQuery({
    queryKey: ["vendor-aliases"],
    queryFn: () => api.listVendorAliases(),
  });
  const [showAdd, setShowAdd] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["vendor-aliases"] });
  function handleErr(e: unknown) {
    if (e instanceof ApiError) setGlobalError(e.detail?.detail || `Error ${e.status}`);
    else setGlobalError((e as Error).message);
    setTimeout(() => setGlobalError(null), 4000);
  }

  // Group by canonical network for a "this is what merges together" view.
  const networks = Array.from(new Set(aliases.map((a) => a.canonical_network))).sort((a, b) => a.localeCompare(b));

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <PageHeader
        title="Vendor Aliases"
        subtitle="Map brand & branch names to one canonical network. All GMS local brands roll up to “GMS”; L&W and ABC Supply roll up to one network. Used by the vendor scraper to merge multi-name distributors."
        icon={<Network className="h-6 w-6 text-primary" />}
        actions={
          <button onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold hover:bg-primary/90 transition">
            <Plus className="h-4 w-4" /> Add alias
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-3 mb-5">
        <StatBox label="Aliases" value={aliases.length} icon={<Network className="h-3.5 w-3.5" />} />
        <StatBox label="Networks" value={networks.length} />
      </div>

      {globalError && (
        <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" /><span>{globalError}</span>
        </div>
      )}

      {isLoading && (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" /> Loading…
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-destructive text-sm">
          Failed to load: {(error as Error).message}
        </div>
      )}
      {!isLoading && aliases.length === 0 && (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No aliases yet. Add one to start merging multi-name distributors.
        </div>
      )}

      <div className="space-y-6">
        {networks.map((net) => (
          <section key={net}>
            <div className="flex items-center gap-2 mb-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{net}</h2>
              <span className="text-xs text-muted-foreground">
                {aliases.filter((a) => a.canonical_network === net).length} alias(es)
              </span>
            </div>
            <div className="space-y-2">
              {aliases.filter((a) => a.canonical_network === net).map((a) => (
                <AliasRow key={a.id} alias={a} onChange={invalidate} onError={handleErr} />
              ))}
            </div>
          </section>
        ))}
      </div>

      {showAdd && <AliasDialog onClose={() => setShowAdd(false)} onSaved={invalidate} />}
    </div>
  );
}

function AliasRow({ alias, onChange, onError }: { alias: VendorAlias; onChange: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const del = useMutation({
    mutationFn: () => api.deleteVendorAlias(alias.id),
    onSuccess: () => { setConfirmDelete(false); onChange(); },
    onError,
  });

  if (editing) return <AliasDialog alias={alias} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onChange(); }} inline />;

  return (
    <div className="rounded-md border bg-card p-3 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="font-medium flex items-center gap-2 flex-wrap">
          {alias.alias}
          {alias.vendor_type && <Badge variant={alias.vendor_type === "big_box_retailer" ? "warning" : "muted"}>{alias.vendor_type.replace(/_/g, " ")}</Badge>}
          {alias.active === false && <Badge variant="muted">inactive</Badge>}
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">
          → {alias.canonical_network}{alias.entity ? ` · ${alias.entity}` : ""}{alias.notes ? ` · ${alias.notes}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {confirmDelete ? (
          <div className="flex items-center gap-2 text-sm">
            <button onClick={() => del.mutate()} disabled={del.isPending}
              className="rounded-md bg-destructive text-destructive-foreground px-2.5 py-1 text-xs font-medium hover:bg-destructive/90 disabled:opacity-50">
              {del.isPending ? "…" : "Delete"}
            </button>
            <button onClick={() => setConfirmDelete(false)} className="rounded-md border px-2.5 py-1 text-xs hover:bg-secondary">Cancel</button>
          </div>
        ) : (
          <>
            <button onClick={() => setEditing(true)} title="Edit"
              className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary text-muted-foreground">
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => setConfirmDelete(true)} title="Delete"
              className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-destructive/10 text-destructive">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function AliasDialog({ alias, onClose, onSaved, inline }: { alias?: VendorAlias; onClose: () => void; onSaved: () => void; inline?: boolean }) {
  const [f, setF] = useState<VendorAliasBody>({
    alias: alias?.alias || "",
    canonical_network: alias?.canonical_network || "",
    entity: alias?.entity || "",
    vendor_type: alias?.vendor_type || "specialty_distributor",
    notes: alias?.notes || "",
    active: alias?.active ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof VendorAliasBody, v: any) => { setF((p) => ({ ...p, [k]: v })); setError(null); };

  const save = useMutation({
    mutationFn: () => {
      const body: VendorAliasBody = { ...f, alias: f.alias.trim(), canonical_network: f.canonical_network.trim() };
      return alias ? api.updateVendorAlias(alias.id, body) : api.createVendorAlias(body);
    },
    onSuccess: onSaved,
    onError: (e) => setError(e instanceof ApiError ? (e.detail?.detail || `Error ${e.status}`) : (e as Error).message),
  });

  const inp = "w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary";
  const body = (
    <div className={inline ? "rounded-md border bg-card p-5" : "w-full max-w-md rounded-xl border bg-card p-6 shadow-xl"} onClick={(e) => e.stopPropagation()}>
      <h2 className="text-lg font-semibold mb-1">{alias ? "Edit alias" : "Add vendor alias"}</h2>
      <p className="text-xs text-muted-foreground mb-4">An alias is a name as it appears in the wild; the network is what it rolls up to.</p>
      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" /><span>{error}</span>
        </div>
      )}
      <div className="space-y-3">
        <label className="block"><span className="text-sm font-medium block mb-1">Alias (name as seen) *</span>
          <input autoFocus value={f.alias} onChange={(e) => set("alias", e.target.value)} placeholder="e.g. Tucker Materials" className={inp} /></label>
        <label className="block"><span className="text-sm font-medium block mb-1">Canonical network *</span>
          <input value={f.canonical_network} onChange={(e) => set("canonical_network", e.target.value)} placeholder="e.g. GMS" className={inp} /></label>
        <label className="block"><span className="text-sm font-medium block mb-1">Legal entity (optional)</span>
          <input value={f.entity} onChange={(e) => set("entity", e.target.value)} placeholder="e.g. Gypsum Management & Supply" className={inp} /></label>
        <label className="block"><span className="text-sm font-medium block mb-1">Vendor type</span>
          <select value={f.vendor_type} onChange={(e) => set("vendor_type", e.target.value)} className={inp}>
            {VENDOR_TYPES.map((t) => <option key={t} value={t}>{t.replace(/_/g, " ")}</option>)}
          </select></label>
        <label className="block"><span className="text-sm font-medium block mb-1">Notes</span>
          <input value={f.notes} onChange={(e) => set("notes", e.target.value)} className={inp} /></label>
        {alias && (
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={f.active !== false} onChange={(e) => set("active", e.target.checked)} /> Active
          </label>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary">Cancel</button>
        <button onClick={() => save.mutate()} disabled={!f.alias.trim() || !f.canonical_network.trim() || save.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50">
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          {alias ? "Save" : "Create"}
        </button>
      </div>
    </div>
  );

  if (inline) return body;
  return <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>{body}</div>;
}
