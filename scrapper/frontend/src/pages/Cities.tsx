import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { MapPin, Plus, X, Trash2, Pencil, Check, Loader2, AlertCircle, Hash, Info } from "lucide-react";
import { api, ApiError, type City } from "@/lib/api";
import { CityDrawer } from "@/components/drawer/CityDrawer";
import { PageHeader, Stat as StatBox } from "@/components/ui-bits";

export default function Cities() {
  const qc = useQueryClient();
  const { data: cities = [], isLoading, error } = useQuery({
    queryKey: ["cities"],
    queryFn: () => api.listCities(),
  });

  const [showAdd, setShowAdd] = useState(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [detailCity, setDetailCity] = useState<City | null>(null);

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["cities"] });
  }

  function handleErr(e: unknown) {
    if (e instanceof ApiError) setGlobalError(e.detail?.detail || `Error ${e.status}`);
    else setGlobalError((e as Error).message);
    setTimeout(() => setGlobalError(null), 4000);
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <PageHeader
        title="Cities & ZIPs"
        subtitle="Target metros + ZIP codes used by the scraper pipeline."
        icon={<MapPin className="h-6 w-6 text-primary" />}
        actions={
          <button
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-sm font-semibold hover:bg-primary/90 transition"
          >
            <Plus className="h-4 w-4" />
            Add city
          </button>
        }
      />

      {/* Summary strip */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        <StatBox label="Cities" value={cities.length} icon={<MapPin className="h-3.5 w-3.5" />} />
        <StatBox
          label="Total ZIPs"
          value={cities.reduce((a, c) => a + c.zips.length, 0)}
          icon={<Hash className="h-3.5 w-3.5" />}
        />
        <StatBox
          label="Avg ZIPs / city"
          value={
            cities.length === 0
              ? 0
              : Math.round((cities.reduce((a, c) => a + c.zips.length, 0) / cities.length) * 10) / 10
          }
          icon={<Hash className="h-3.5 w-3.5" />}
        />
      </div>

      {globalError && (
        <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
          <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
          <span>{globalError}</span>
        </div>
      )}

      {/* Loading / empty / error */}
      {isLoading && (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          <Loader2 className="h-5 w-5 animate-spin inline-block mr-2" />
          Loading cities…
        </div>
      )}
      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-destructive text-sm">
          Failed to load cities: {(error as Error).message}
        </div>
      )}
      {!isLoading && cities.length === 0 && (
        <div className="rounded-lg border bg-card p-10 text-center text-muted-foreground text-sm">
          No cities yet. Click "Add city" to create one.
        </div>
      )}

      {/* City grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {cities.map((c) => (
          <CityCard
            key={c.id}
            city={c}
            onChange={invalidate}
            onError={handleErr}
            onOpenDetail={() => setDetailCity(c)}
          />
        ))}
      </div>

      <CityDrawer city={detailCity} open={!!detailCity} onClose={() => setDetailCity(null)} />

      {showAdd && <AddCityDialog onClose={() => setShowAdd(false)} onCreated={invalidate} onError={handleErr} />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
function CityCard({
  city,
  onChange,
  onError,
  onOpenDetail,
}: {
  city: City;
  onChange: () => void;
  onError: (e: unknown) => void;
  onOpenDetail: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(city.name);
  const [state, setState] = useState(city.state);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showAddZip, setShowAddZip] = useState(false);

  const save = useMutation({
    mutationFn: () => api.updateCity(city.id, { name, state }),
    onSuccess: () => {
      setEditing(false);
      onChange();
    },
    onError,
  });

  const del = useMutation({
    mutationFn: () => api.deleteCity(city.id),
    onSuccess: () => {
      setConfirmDelete(false);
      onChange();
    },
    onError,
  });

  const removeZip = useMutation({
    mutationFn: (z: string) => api.removeZip(city.id, z),
    onSuccess: onChange,
    onError,
  });

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b flex items-start justify-between gap-3">
        {editing ? (
          <div className="flex-1 flex gap-2">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="flex-1 rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="City name"
            />
            <input
              value={state}
              onChange={(e) => setState(e.target.value.toUpperCase())}
              maxLength={2}
              className="w-14 rounded-md border bg-background px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              placeholder="ST"
            />
          </div>
        ) : (
          <div>
            <div className="font-semibold text-lg leading-tight">{city.name}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {city.state} · {city.zips.length} ZIP{city.zips.length === 1 ? "" : "s"}
            </div>
          </div>
        )}
        <div className="flex items-center gap-1 shrink-0">
          {editing ? (
            <>
              <button
                onClick={() => save.mutate()}
                disabled={save.isPending}
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary text-primary"
                title="Save"
              >
                {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-4 w-4" />}
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setName(city.name);
                  setState(city.state);
                }}
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary"
                title="Cancel"
              >
                <X className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={onOpenDetail}
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary text-muted-foreground"
                title="View details"
              >
                <Info className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setEditing(true)}
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-secondary text-muted-foreground"
                title="Rename"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => setConfirmDelete(true)}
                className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-destructive/10 text-destructive"
                title="Delete city"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
      </div>

      {/* ZIP chips */}
      <div className="p-4">
        <div className="flex flex-wrap gap-1.5">
          {city.zips.map((z) => (
            <span
              key={z}
              className="group inline-flex items-center gap-1 rounded-full bg-secondary text-secondary-foreground px-2.5 py-1 text-xs font-mono"
            >
              {z}
              <button
                onClick={() => removeZip.mutate(z)}
                className="opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity"
                title={`Remove ${z}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <button
            onClick={() => setShowAddZip(true)}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-border text-muted-foreground hover:text-primary hover:border-primary px-2.5 py-1 text-xs font-medium transition"
            title="Add ZIP"
          >
            <Plus className="h-3 w-3" />
            Add ZIP
          </button>
        </div>
        {city.zips.length === 0 && (
          <div className="text-xs text-muted-foreground italic mt-2">No ZIPs yet.</div>
        )}
      </div>

      {showAddZip && (
        <AddZipDialog
          cityId={city.id}
          cityName={city.name}
          existingZips={city.zips}
          onClose={() => setShowAddZip(false)}
          onAdded={onChange}
          onError={onError}
        />
      )}

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="border-t bg-destructive/5 p-3 text-sm flex items-center gap-3">
          <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
          <span className="flex-1">Delete {city.name} and all its ZIPs?</span>
          <button
            onClick={() => del.mutate()}
            disabled={del.isPending}
            className="rounded-md bg-destructive text-destructive-foreground px-3 py-1 text-xs font-medium hover:bg-destructive/90 disabled:opacity-50"
          >
            {del.isPending ? "Deleting…" : "Yes, delete"}
          </button>
          <button
            onClick={() => setConfirmDelete(false)}
            className="rounded-md border px-3 py-1 text-xs font-medium hover:bg-secondary"
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
function AddZipDialog({
  cityId,
  cityName,
  existingZips,
  onClose,
  onAdded,
  onError,
}: {
  cityId: string;
  cityName: string;
  existingZips: string[];
  onClose: () => void;
  onAdded: () => void;
  onError: (e: unknown) => void;
}) {
  const [raw, setRaw] = useState("");

  const parsed = raw
    .split(/[\s,]+/)
    .map((z) => z.trim())
    .filter(Boolean);
  const duplicates = parsed.filter((z) => existingZips.includes(z));
  const toAdd = parsed.filter((z) => !existingZips.includes(z));

  const addZips = useMutation({
    mutationFn: async () => {
      for (const z of toAdd) {
        await api.addZip(cityId, z);
      }
    },
    onSuccess: () => {
      onAdded();
      onClose();
    },
    onError,
  });

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border bg-card p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold mb-1">Add ZIP to {cityName}</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Enter one or more ZIP codes. Comma- or space-separated.
        </p>

        <input
          autoFocus
          value={raw}
          onChange={(e) => setRaw(e.target.value.replace(/[^0-9,\s-]/g, ""))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && toAdd.length > 0 && !addZips.isPending) {
              e.preventDefault();
              addZips.mutate();
            }
          }}
          placeholder="e.g. 33602, 33603, 33604"
          className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
        />

        {duplicates.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Already in list: <span className="font-mono">{duplicates.join(", ")}</span>
          </p>
        )}
        {toAdd.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Will add {toAdd.length} ZIP{toAdd.length === 1 ? "" : "s"}.
          </p>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary"
          >
            Cancel
          </button>
          <button
            onClick={() => addZips.mutate()}
            disabled={toAdd.length === 0 || addZips.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
          >
            {addZips.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add
          </button>
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
function AddCityDialog({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: () => void;
  onError: (e: unknown) => void;
}) {
  const [name, setName] = useState("");
  const [state, setState] = useState("FL");
  const [zipsRaw, setZipsRaw] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.createCity({
        name: name.trim(),
        state: state.toUpperCase().trim(),
        zips: zipsRaw
          .split(/[\s,]+/)
          .map((z) => z.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      onCreated();
      onClose();
    },
    onError,
  });

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border bg-card p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold mb-1">Add city</h2>
        <p className="text-xs text-muted-foreground mb-4">
          Cities + ZIPs feed the scraper. ZIPs can be added later too.
        </p>

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium block mb-1">Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Sarasota"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">State</label>
            <input
              value={state}
              onChange={(e) => setState(e.target.value.toUpperCase())}
              maxLength={2}
              className="w-20 rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">ZIP codes (optional)</label>
            <textarea
              value={zipsRaw}
              onChange={(e) => setZipsRaw(e.target.value)}
              placeholder="34230, 34231, 34232"
              rows={3}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <p className="text-xs text-muted-foreground mt-1">Comma- or space-separated.</p>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="rounded-md border px-4 py-2 text-sm font-medium hover:bg-secondary"
          >
            Cancel
          </button>
          <button
            onClick={() => create.mutate()}
            disabled={!name.trim() || create.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-semibold hover:bg-primary/90 disabled:opacity-50"
          >
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
