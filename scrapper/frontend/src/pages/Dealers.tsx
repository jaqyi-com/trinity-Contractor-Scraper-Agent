import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Store, Plus, Trash2, Pencil, Check, X, Loader2, AlertCircle, MapPin } from "lucide-react";
import { api, ApiError, type Dealer, type DealerBody } from "@/lib/api";
import { PageHeader, Stat as StatBox, Badge } from "@/components/ui-bits";

// Dealer/vendor ACCOUNTS — the client's account locations (may include a Home
// Depot). They anchor the TN contractor 50-mile radius: each account's address is
// geocoded, then contractors within the radius are scraped. (Vendor scraping, by
// contrast, anchors on city centers — that's separate.)
export default function Dealers() {
  const qc = useQueryClient();
  const { data: dealers = [], isLoading, error } = useQuery({
    queryKey: ["dealers"],
    queryFn: () => api.listDealers(),
  });
  const [showAdd, setShowAdd] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["dealers"] });
  function handleErr(e: unknown) {
    if (e instanceof ApiError) setGlobalError(e.detail?.detail || `Error ${e.status}`);
    else setGlobalError((e as Error).message);
    setTimeout(() => setGlobalError(null), 4000);
  }

  const geocoded = dealers.filter((d) => d.lat != null && d.lng != null).length;

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <PageHeader
        title="Dealer / Vendor Accounts"
        subtitle="Your account locations (can include a Home Depot). These anchor the Tennessee contractor radius — each address is geocoded, then contractors within the radius are scraped. Manage the radius in Dashboard → Run configuration."
        icon={<Store className="h-6 w-6 text-primary" />}
        actions={
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold hover:bg-primary/90 transition"
          >
            <Plus className="h-4 w-4" /> Add account
          </button>
        }
      />

      <div className="grid grid-cols-3 gap-3 mb-5">
        <StatBox label="Accounts" value={dealers.length} icon={<Store className="h-3.5 w-3.5" />} />
        <StatBox label="Geocoded" value={geocoded} icon={<MapPin className="h-3.5 w-3.5" />} />
        <StatBox label="Big-box" value={dealers.filter((d) => d.is_big_box).length} />
      </div>

      {globalError && (
        <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{globalError}</span>
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
      {!isLoading && dealers.length === 0 && (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No accounts yet. Add one — give it an address and it will be geocoded automatically.
        </div>
      )}

      <div className="space-y-3">
        {dealers.map((d) => (
          <DealerRow key={d.id} dealer={d} onChange={invalidate} onError={handleErr} />
        ))}
      </div>

      {showAdd && <DealerDialog onClose={() => setShowAdd(false)} onSaved={invalidate} />}
    </div>
  );
}

function DealerRow({ dealer, onChange, onError }: { dealer: Dealer; onChange: () => void; onError: (e: unknown) => void }) {
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const del = useMutation({
    mutationFn: () => api.deleteDealer(dealer.id),
    onSuccess: () => { setConfirmDelete(false); onChange(); },
    onError,
  });

  if (editing) {
    return <DealerDialog dealer={dealer} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); onChange(); }} inline />;
  }

  const loc = [dealer.address || [dealer.city, dealer.state, dealer.zip_code].filter(Boolean).join(", ")].filter(Boolean).join(" · ");
  return (
    <div className="rounded-lg border bg-card p-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="font-semibold flex items-center gap-2 flex-wrap">
          {dealer.name}
          {dealer.is_big_box && <Badge variant="warning">big-box</Badge>}
          {dealer.active === false && <Badge variant="muted">inactive</Badge>}
        </div>
        <div className="text-xs text-muted-foreground mt-1 truncate">{loc || "—"}</div>
        <div className="text-xs mt-1">
          {dealer.lat != null && dealer.lng != null ? (
            <span className="text-emerald-700">
              <MapPin className="h-3 w-3 inline-block -mt-0.5" /> {dealer.lat.toFixed(4)}, {dealer.lng.toFixed(4)}
            </span>
          ) : (
            <span className="text-amber-700">not geocoded — add/fix the address so the radius can use it</span>
          )}
          {dealer.radius_miles != null && <span className="text-muted-foreground"> · radius {dealer.radius_miles} mi</span>}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {confirmDelete ? (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Delete?</span>
            <button onClick={() => del.mutate()} disabled={del.isPending}
              className="rounded-md bg-destructive text-destructive-foreground px-2.5 py-1 text-xs font-medium hover:bg-destructive/90 disabled:opacity-50">
              {del.isPending ? "…" : "Yes"}
            </button>
            <button onClick={() => setConfirmDelete(false)} className="rounded-md border px-2.5 py-1 text-xs hover:bg-secondary">No</button>
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

function DealerDialog({ dealer, onClose, onSaved, inline }: { dealer?: Dealer; onClose: () => void; onSaved: () => void; inline?: boolean }) {
  const [f, setF] = useState<DealerBody>({
    name: dealer?.name || "",
    address: dealer?.address || "",
    city: dealer?.city || "",
    state: dealer?.state || "TN",
    zip_code: dealer?.zip_code || "",
    radius_miles: dealer?.radius_miles ?? null,
    is_big_box: dealer?.is_big_box || false,
    notes: dealer?.notes || "",
    active: dealer?.active ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof DealerBody, v: any) => { setF((p) => ({ ...p, [k]: v })); setError(null); };

  const save = useMutation({
    mutationFn: () => {
      const body: DealerBody = { ...f, name: (f.name || "").trim(), state: (f.state || "TN").toUpperCase() };
      return dealer ? api.updateDealer(dealer.id, body) : api.createDealer(body);
    },
    onSuccess: onSaved,
    onError: (e) => setError(e instanceof ApiError ? (e.detail?.detail || `Error ${e.status}`) : (e as Error).message),
  });

  const body = (
    <div className={inline ? "rounded-lg border bg-card p-5" : "w-full max-w-lg rounded-xl border bg-card p-6 shadow-xl"} onClick={(e) => e.stopPropagation()}>
      <h2 className="text-lg font-semibold mb-1">{dealer ? "Edit account" : "Add dealer / vendor account"}</h2>
      <p className="text-xs text-muted-foreground mb-4">
        Give an address (or city + state + ZIP) — it’s geocoded on save so the contractor radius can use it.
        Leave radius blank to use the global contractor radius.
      </p>
      {error && (
        <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" /><span>{error}</span>
        </div>
      )}
      <div className="space-y-3">
        <Field label="Name *"><input autoFocus value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Home Depot — Murfreesboro" className={inp} /></Field>
        <Field label="Address"><input value={f.address} onChange={(e) => set("address", e.target.value)} placeholder="123 Main St, Murfreesboro, TN 37130" className={inp} /></Field>
        <div className="flex gap-3">
          <Field label="City"><input value={f.city} onChange={(e) => set("city", e.target.value)} className={inp} /></Field>
          <div className="w-20"><Field label="State"><input value={f.state} maxLength={2} onChange={(e) => set("state", e.target.value.toUpperCase())} className={inp + " font-mono"} /></Field></div>
          <div className="w-28"><Field label="ZIP"><input value={f.zip_code} onChange={(e) => set("zip_code", e.target.value)} className={inp + " font-mono"} /></Field></div>
        </div>
        <div className="flex gap-6 items-center">
          <div className="w-32"><Field label="Radius (mi)"><input type="number" min={1} max={500} value={f.radius_miles ?? ""} placeholder="default" onChange={(e) => set("radius_miles", e.target.value === "" ? null : Number(e.target.value))} className={inp} /></Field></div>
          <label className="flex items-center gap-2 text-sm mt-5 cursor-pointer">
            <input type="checkbox" checked={!!f.is_big_box} onChange={(e) => set("is_big_box", e.target.checked)} />
            Big-box retailer (Home Depot / Lowe’s)
          </label>
        </div>
        <Field label="Notes"><input value={f.notes} onChange={(e) => set("notes", e.target.value)} className={inp} /></Field>
        {dealer && (
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input type="checkbox" checked={f.active !== false} onChange={(e) => set("active", e.target.checked)} /> Active
          </label>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <button onClick={onClose} className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary">Cancel</button>
        <button onClick={() => save.mutate()} disabled={!f.name?.trim() || save.isPending}
          className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50">
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          {dealer ? "Save" : "Create"}
        </button>
      </div>
    </div>
  );

  if (inline) return body;
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      {body}
    </div>
  );
}

const inp = "w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary";
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block flex-1">
      <span className="text-sm font-medium block mb-1">{label}</span>
      {children}
    </label>
  );
}
