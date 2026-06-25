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

      {/* Cities grouped by state — Florida and Tennessee in their own sub-sections */}
      {(() => {
        const STATE_LABEL: Record<string, string> = { FL: "Florida", TN: "Tennessee" };
        const ORDER = ["FL", "TN"];
        const states = Array.from(new Set(cities.map((c) => c.state)))
          .sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b));
        return states.map((st) => {
          const group = cities.filter((c) => c.state === st);
          const zipCount = group.reduce((a, c) => a + c.zips.length, 0);
          return (
            <section key={st} className="mb-8">
              <div className="flex items-center gap-2 mb-3">
                <span className="inline-flex items-center justify-center rounded-md bg-primary/10 text-primary text-xs font-bold px-2 py-1">
                  {st}
                </span>
                <h2 className="text-lg font-semibold">{STATE_LABEL[st] || st}</h2>
                <span className="text-xs text-muted-foreground">
                  {group.length} cit{group.length === 1 ? "y" : "ies"} · {zipCount} ZIPs
                </span>
              </div>
              {(() => {
                const renderGrid = (list: City[]) => (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {list.map((c) => (
                      <CityCard
                        key={c.id}
                        city={c}
                        onChange={invalidate}
                        onError={handleErr}
                        onOpenDetail={() => setDetailCity(c)}
                      />
                    ))}
                  </div>
                );
                const hasTiers = group.some((c) => c.tier != null);
                if (!hasTiers) return renderGrid(group);
                const tier1 = group.filter((c) => c.tier === 1);
                const tier2 = group.filter((c) => c.tier === 2);
                const untiered = group.filter((c) => c.tier == null);
                const TIER_SUB: { list: City[]; label: string }[] = [
                  { list: tier1, label: "Tier 1 — Named priority cities (scraped first)" },
                  { list: tier2, label: "Tier 2 — Population ≥ 50,000" },
                  { list: untiered, label: "Other" },
                ];
                return (
                  <div className="space-y-5">
                    {TIER_SUB.filter((t) => t.list.length > 0).map((t) => (
                      <div key={t.label}>
                        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                          {t.label} · {t.list.length}
                        </div>
                        {renderGrid(t.list)}
                      </div>
                    ))}
                  </div>
                );
              })()}
            </section>
          );
        });
      })()}

      {/* Excluded regions */}
      <ExclusionsPanel cities={cities} onError={handleErr} />

      <CityDrawer city={detailCity} open={!!detailCity} onClose={() => setDetailCity(null)} />

      {showAdd && <AddCityDialog onClose={() => setShowAdd(false)} onCreated={invalidate} onError={handleErr} />}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Excluded regions — locked base rules (Memphis metro, read-only) + user-added
// cities. Users pick a city from a dropdown (no free text); it resolves to ZIPs
// the scraper drops. Locked rules can't be removed.
// ──────────────────────────────────────────────────────────────
function ExclusionsPanel({ cities, onError }: { cities: City[]; onError: (e: unknown) => void }) {
  const qc = useQueryClient();
  const { data: exclusions = [] } = useQuery({
    queryKey: ["exclusions"],
    queryFn: () => api.listExclusions(),
  });
  const [pick, setPick] = useState("");

  const invalidate = () => qc.invalidateQueries({ queryKey: ["exclusions"] });
  const add = useMutation({
    mutationFn: (city: string) => api.addExclusion(city, "TN"),
    onSuccess: () => { setPick(""); invalidate(); },
    onError,
  });
  const del = useMutation({
    mutationFn: (id: number) => api.deleteExclusion(id),
    onSuccess: invalidate,
    onError,
  });

  // Cities available to exclude = not already excluded.
  const excludedNames = new Set(exclusions.flatMap((e) => e.match_values.map((m) => m.toLowerCase())));
  const options = cities
    .filter((c) => !excludedNames.has(c.name.toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="mt-8 rounded-lg border bg-card p-5">
      <div className="flex items-center gap-2 mb-1">
        <X className="h-4 w-4 text-destructive" />
        <h2 className="font-semibold">Excluded regions</h2>
      </div>
      <p className="text-xs text-muted-foreground mb-4">
        These cities (and their ZIPs) are never scraped or returned. The Memphis metro is a locked
        base rule. Add more from the dropdown — they resolve to ZIP codes automatically.
      </p>

      {/* Add via dropdown (no free text) */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select
          value={pick}
          onChange={(e) => setPick(e.target.value)}
          className="rounded-md border bg-background px-3 py-2 text-sm min-w-[220px]"
        >
          <option value="">Select a city to exclude…</option>
          {options.map((c) => (
            <option key={c.id} value={c.name}>
              {c.name} ({c.state})
            </option>
          ))}
        </select>
        <button
          onClick={() => pick && add.mutate(pick)}
          disabled={!pick || add.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-2 text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition"
        >
          <Plus className="h-4 w-4" /> Exclude
        </button>
      </div>

      {/* List */}
      <div className="space-y-2">
        {exclusions.length === 0 && (
          <div className="text-sm text-muted-foreground">No exclusions.</div>
        )}
        {exclusions.map((e) => (
          <div key={e.id} className="flex items-start justify-between gap-3 rounded-md border p-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium">
                {e.locked && <span title="Locked base rule">🔒</span>}
                {e.region_name}
                <span className="text-[10px] uppercase rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                  {e.state}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mt-1 truncate">
                {e.match_values.join(", ")} · {e.zip_codes.length} ZIP{e.zip_codes.length === 1 ? "" : "s"}
              </div>
            </div>
            {e.locked ? (
              <span className="text-[10px] text-muted-foreground shrink-0 mt-1">locked</span>
            ) : (
              <button
                onClick={() => del.mutate(e.id)}
                disabled={del.isPending}
                className="text-destructive hover:bg-destructive/10 rounded p-1.5 shrink-0"
                title="Remove exclusion"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>
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
            <div className="font-semibold text-lg leading-tight flex items-center gap-2">
              {city.name}
              {city.tier != null && (
                <span
                  className={`text-[10px] font-bold rounded px-1.5 py-0.5 ${
                    city.tier === 1
                      ? "bg-amber-100 text-amber-800"
                      : "bg-slate-100 text-slate-600"
                  }`}
                  title={city.tier === 1 ? "Tier 1 — named priority city" : "Tier 2 — population ≥ 50k"}
                >
                  Tier {city.tier}
                </span>
              )}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {city.state} · {city.zips.length} ZIP{city.zips.length === 1 ? "" : "s"}
              {city.county ? ` · ${city.county} County` : ""}
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
  cityId: number;
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
  const [error, setError] = useState<string | null>(null);

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
    onError: (e) => {
      // Show errors only inside this dialog (not the parent's global banner,
      // which would duplicate the message behind the modal backdrop).
      if (e instanceof ApiError) {
        setError(
          e.status === 409
            ? e.detail?.detail || "This city already exists."
            : e.detail?.detail || `Error ${e.status}`,
        );
      } else {
        setError((e as Error).message);
      }
    },
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

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-md bg-destructive/10 text-destructive p-3 text-sm">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium block mb-1">Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => { setName(e.target.value); setError(null); }}
              placeholder="e.g. Sarasota"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <div>
            <label className="text-sm font-medium block mb-1">State</label>
            <input
              value={state}
              onChange={(e) => { setState(e.target.value.toUpperCase()); setError(null); }}
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
