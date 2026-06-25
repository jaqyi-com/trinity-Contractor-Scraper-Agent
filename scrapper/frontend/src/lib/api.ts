// Typed fetch wrappers for the backend API.
// Every request attaches the JWT from localStorage; 401 clears the token and
// redirects to /login.

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const TOKEN_KEY = "auth_token";

export class ApiError extends Error {
  constructor(public status: number, public detail: any, message: string) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

/** Build query string. Arrays produce repeated keys (?city=A&city=B). */
export function qs(params: Record<string, any>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      v.forEach((x) => x != null && x !== "" && u.append(k, String(x)));
    } else {
      u.append(k, String(v));
    }
  }
  const s = u.toString();
  return s ? `?${s}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) || {}),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (res.status === 401) {
    tokenStore.clear();
    if (!path.startsWith("/api/auth/login") && location.pathname !== "/login") {
      location.assign("/login");
    }
  }

  if (!res.ok) {
    let detail: any = null;
    try { detail = await res.json(); } catch { detail = await res.text().catch(() => ""); }
    throw new ApiError(res.status, detail, `API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// ── Types ──
export type Paged<T> = { total: number; limit: number; offset: number; rows: T[] };
export type FacetItem = { value: string; n: number };

export type Contractor = {
  id: number;
  business_name: string;
  // record type + territory tags (vendors live in the same table as contractors)
  record_type: string | null;          // "contractor" | "vendor" (null = legacy contractor)
  state: string | null;
  county: string | null;
  city_tier: string | number | null;   // geographic tier (1/2), distinct from the classification `tier`
  source: string | null;
  // vendor-only fields (empty on contractor rows)
  is_big_box: boolean | null;
  vendor_type: string | null;          // specialty_distributor | big_box_retailer | independent
  canonical_network: string | null;    // GMS, L&W Supply, … (rolled-up entity)
  // status flags
  excluded_reason: string | null;      // e.g. lumber:category:lumberyard
  out_of_territory: boolean | null;
  city: string | null;
  zip_code: string | null;
  address: string | null;
  tier: string | null;
  specialty_keywords: string[] | null;
  google_categories: string[] | null;
  services_listed: string[] | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  owner_name: string | null;
  license_status: string | null;
  license_numbers: string[] | null;
  license_categories: string[] | null;
  google_rating: number | null;
  google_review_count: number | null;
  bbb_rating: string | null;
  bbb_accredited: boolean | null;
  years_in_business: number | null;
  social_profiles: Record<string, string> | null;
  sources: string[] | null;
  place_ids: string[] | null;
  scraped_at: string;
  job_id: string;
};

/** Full query surface for the contractor grid + CSV export.
 * Mirrors the backend `ContractorFilters` dependency — every column filterable. */
export type ContractorQuery = {
  job_id?: string;
  // enum facets (repeated query params)
  city?: string[];
  tier?: string[];
  license_status?: string[];
  // global multi-field search
  search?: string;
  // scalar text "contains"
  business_name?: string;
  zip_code?: string;
  address?: string;
  owner_name?: string;
  bbb_rating?: string;
  // JSONB array "contains"
  specialty_keywords?: string;
  google_categories?: string;
  services_listed?: string;
  license_numbers?: string;
  license_categories?: string;
  sources?: string;
  place_ids?: string;
  // presence toggles
  has_email?: boolean;
  has_phone?: boolean;
  has_website?: boolean;
  bbb_accredited?: boolean;
  // numeric minimums
  min_rating?: number;
  min_review_count?: number;
  min_years?: number;
  // sort + pagination
  sort_by?: string;
  sort_dir?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type ClassificationLog = {
  id: number;
  job_id: string;
  contractor_id: number | null;
  business_name: string | null;
  place_id: string | null;
  decision: "INCLUDED" | "EXCLUDED";
  assigned_tier: string | null;
  matched_keywords: { tier?: string; keyword: string }[] | null;
  exclusion_keywords: { tier?: string; keyword: string }[] | null;
  classifier_text: string | null;
  reason: string | null;
  created_at: string;
};

export type Keyword = {
  id: number;
  tier: string;
  keyword: string;
  active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
  created_by: string | null;
};

export type City = {
  id: number;
  name: string;
  state: string;
  zips: string[];
  created_at: string;
  updated_at: string;
  tier?: number | null;
  county?: string | null;
};

export type Exclusion = {
  id: number;
  state: string;
  region_name: string;
  match_values: string[];
  zip_codes: string[];
  locked: boolean;
};

export type StageBatch = {
  batch: string;
  batch_name: string;
  stages: Record<string, number>;
};

export type StageRecord = {
  id: number;
  batch: string;
  stage: string;
  record_type: string;
  state: string | null;
  city: string | null;
  city_tier: string | null;
  zip_code: string | null;
  source: string | null;
  business_name: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  excluded_reason: string | null;
};

export type Settings = {
  max_final_records: number;
  default_max_final_records: number;
  // Per-service USD cost budgets for the next run. null = unlimited.
  discovery_budget_usd: number | null;
  bbb_budget_usd: number | null;
  apollo_budget_usd: number | null;
  // TN search radii (miles).
  vendor_radius_miles: number;
  contractor_radius_miles: number;
  // Optional statewide TN verify-a-name license enrichment (slow; default off).
  enable_tn_verify: boolean;
};

export type UpdateSettingsBody = {
  max_final_records: number;
  discovery_budget_usd?: number | null;
  bbb_budget_usd?: number | null;
  apollo_budget_usd?: number | null;
  vendor_radius_miles?: number | null;
  contractor_radius_miles?: number | null;
  enable_tn_verify?: boolean | null;
};

// Dealer/vendor account locations — anchor the TN contractor 50-mi radius.
export type Dealer = {
  id: number;
  client_id: string | null;
  name: string;
  address: string | null;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  lat: number | null;
  lng: number | null;
  radius_miles: number | null;
  is_big_box: boolean | null;
  active: boolean | null;
  notes: string | null;
};
export type DealerBody = {
  name: string;
  address?: string;
  city?: string;
  state?: string;
  zip_code?: string;
  lat?: number | null;
  lng?: number | null;
  radius_miles?: number | null;
  is_big_box?: boolean;
  notes?: string;
  active?: boolean;
};

// Vendor alias / subsidiary map — rolls brand/branch names up to one network.
export type VendorAlias = {
  id: number;
  alias: string;
  canonical_network: string;
  entity: string | null;
  vendor_type: string | null;
  active: boolean | null;
  notes: string | null;
};
export type VendorAliasBody = {
  alias: string;
  canonical_network: string;
  entity?: string;
  vendor_type?: string;
  notes?: string;
  active?: boolean;
};

// ── API surface ──
export const api = {
  // Auth
  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; token_type: string; user: { id: number; email: string; name: string } }>(
      "/api/auth/login",
      { method: "POST", body: JSON.stringify(body) },
    ),
  me: () => request<{ email: string; name?: string; user_id?: number }>("/api/auth/me"),

  // Settings
  getSettings: () => request<Settings>("/api/settings"),
  updateSettings: (body: UpdateSettingsBody) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),

  // Jobs
  startJob: (body?: { mode?: string; territory?: string }) =>
    request<{ job_id: string; status: string; mode?: string; territory?: string }>(
      "/api/jobs/start",
      { method: "POST", body: JSON.stringify(body ?? { mode: "contractor", territory: "FL" }) },
    ),
  stopJob: (jobId: string) =>
    request<{ job_id: string; status: string; stop_requested: boolean }>(
      `/api/jobs/${jobId}/stop`, { method: "POST" },
    ),
  resumeJob: (jobId: string) =>
    request<{ job_id: string; status: string; resume_from: string | null }>(
      `/api/jobs/${jobId}/resume`, { method: "POST" },
    ),
  cancelJob: (jobId: string) =>
    request<{ job_id: string; status: string }>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  getJobStatus: (jobId: string) => request<any>(`/api/jobs/${jobId}/status`),
  listJobs: () => request<any[]>("/api/jobs"),
  getCurrentJob: () => request<any | null>("/api/jobs/current"),

  // Keywords
  listKeywords: (params: { tier?: string; search?: string; active?: boolean } = {}) =>
    request<Keyword[]>(`/api/keywords${qs(params)}`),
  keywordFacets: () => request<{ value: string; n: number; n_active: number }[]>("/api/keywords/facets"),
  getKeyword: (id: number) => request<Keyword>(`/api/keywords/${id}`),
  createKeyword: (body: { tier: string; keyword: string; notes?: string; reason?: string }) =>
    request<Keyword>("/api/keywords", { method: "POST", body: JSON.stringify(body) }),
  updateKeyword: (id: number, body: { keyword?: string; active?: boolean; notes?: string; reason?: string }) =>
    request<Keyword>(`/api/keywords/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteKeyword: (id: number, reason?: string) =>
    request<any>(`/api/keywords/${id}`, { method: "DELETE", body: JSON.stringify({ reason }) }),
  keywordHistory: (id: number) => request<any[]>(`/api/keywords/${id}/history`),

  // Cities
  listCities: () => request<City[]>("/api/cities"),
  getCity: (id: number) => request<City>(`/api/cities/${id}`),
  createCity: (body: { name: string; state?: string; zips?: string[] }) =>
    request<City>("/api/cities", { method: "POST", body: JSON.stringify(body) }),
  updateCity: (id: number, body: { name?: string; state?: string }) =>
    request<City>(`/api/cities/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteCity: (id: number) => request<{ deleted: number }>(`/api/cities/${id}`, { method: "DELETE" }),
  addZip: (cityId: number, zip: string) =>
    request<City>(`/api/cities/${cityId}/zips`, { method: "POST", body: JSON.stringify({ zip_code: zip }) }),
  removeZip: (cityId: number, zip: string) =>
    request<City>(`/api/cities/${cityId}/zips/${encodeURIComponent(zip)}`, { method: "DELETE" }),

  // Pipeline stages (Workstream E)
  stageOrder: () => request<{ stages: string[] }>("/api/stages/order"),
  stageBatches: () => request<StageBatch[]>("/api/stages/batches"),
  stageRecords: (batch: string, stage: string, limit = 1000) =>
    request<{ batch: string; stage: string; total: number; rows: StageRecord[] }>(
      `/api/stages/records${qs({ batch, stage, limit })}`,
    ),

  // Dealer/vendor accounts (contractor radius anchors)
  listDealers: () => request<Dealer[]>("/api/dealers"),
  createDealer: (body: DealerBody) =>
    request<Dealer>("/api/dealers", { method: "POST", body: JSON.stringify(body) }),
  updateDealer: (id: number, body: DealerBody) =>
    request<Dealer>(`/api/dealers/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteDealer: (id: number) =>
    request<{ deleted: boolean; id: number }>(`/api/dealers/${id}`, { method: "DELETE" }),

  // Vendor alias / subsidiary map
  listVendorAliases: () => request<VendorAlias[]>("/api/vendor-aliases"),
  createVendorAlias: (body: VendorAliasBody) =>
    request<VendorAlias>("/api/vendor-aliases", { method: "POST", body: JSON.stringify(body) }),
  updateVendorAlias: (id: number, body: VendorAliasBody) =>
    request<VendorAlias>(`/api/vendor-aliases/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteVendorAlias: (id: number) =>
    request<{ deleted: boolean; id: number }>(`/api/vendor-aliases/${id}`, { method: "DELETE" }),

  // Excluded regions (territory exclusions)
  listExclusions: (state?: string) =>
    request<Exclusion[]>(`/api/exclusions${qs({ state })}`),
  addExclusion: (city: string, state = "TN") =>
    request<Exclusion>("/api/exclusions", { method: "POST", body: JSON.stringify({ city, state }) }),
  deleteExclusion: (id: number) =>
    request<{ deleted: boolean; id: number }>(`/api/exclusions/${id}`, { method: "DELETE" }),

  // Contractors
  listContractors: (params: ContractorQuery = {}) =>
    request<Paged<Contractor>>(`/api/contractors${qs(params)}`),
  contractorFacets: (jobId?: string) =>
    request<{ total: number; cities: FacetItem[]; tiers: FacetItem[]; license_statuses: FacetItem[] }>(
      `/api/contractors/facets${qs({ job_id: jobId })}`,
    ),
  getContractor: (id: number) => request<Contractor>(`/api/contractors/${id}`),
  contractorClassification: (id: number) =>
    request<ClassificationLog[]>(`/api/contractors/${id}/classification`),

  exportContractors: async (
    params: Omit<ContractorQuery, "limit" | "offset"> & { format?: "csv" | "xlsx" } = {},
  ) => {
    const token = tokenStore.get();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${API_URL}/api/contractors/export${qs(params)}`, { headers });
    if (res.status === 401) {
      tokenStore.clear();
      if (location.pathname !== "/login") location.assign("/login");
      throw new ApiError(401, null, "Unauthorized");
    }
    if (!res.ok) {
      let detail: any = null;
      try { detail = await res.json(); } catch { detail = await res.text().catch(() => ""); }
      throw new ApiError(res.status, detail, `Export ${res.status}: ${res.statusText}`);
    }

    const blob = await res.blob();
    const ext = params.format === "xlsx" ? "xlsx" : "csv";
    const filename =
      res.headers.get("Content-Disposition")?.match(/filename="?([^"]+)"?/)?.[1] ||
      `contractors_${new Date().toISOString().slice(0, 10)}.${ext}`;

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  // Classification log
  listClassificationLog: (params: {
    job_id?: string;
    decision?: string[];
    tier?: string[];
    search?: string;
    sort_by?: string;
    sort_dir?: "asc" | "desc";
    limit?: number;
    offset?: number;
  } = {}) => request<Paged<ClassificationLog>>(`/api/classification-log${qs(params)}`),
  classificationFacets: (jobId?: string) =>
    request<{ total: number; decisions: FacetItem[]; tiers: FacetItem[] }>(
      `/api/classification-log/facets${qs({ job_id: jobId })}`,
    ),
  classificationStats: (jobId?: string) =>
    request<any>(`/api/classification-log/stats${qs({ job_id: jobId })}`),
  getClassificationLog: (id: number) => request<ClassificationLog>(`/api/classification-log/${id}`),

  health: () => request<{ status: string; db: string }>("/api/health"),
};
