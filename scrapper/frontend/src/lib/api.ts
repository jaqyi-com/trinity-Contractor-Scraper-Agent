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
};

export type Settings = {
  max_final_records: number;
  default_max_final_records: number;
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
  updateSettings: (body: { max_final_records: number }) =>
    request<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),

  // Jobs
  startJob: () => request<{ job_id: string; status: string }>("/api/jobs/start", { method: "POST" }),
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

  exportContractors: async (params: Omit<ContractorQuery, "limit" | "offset"> = {}) => {
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
    const filename =
      res.headers.get("Content-Disposition")?.match(/filename="?([^"]+)"?/)?.[1] ||
      `contractors_${new Date().toISOString().slice(0, 10)}.csv`;

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
