/** Thin, typed client for the FastAPI backend (proxied at /api). */

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string,
  ) {
    super(message);
  }

  /** Human-readable list of field errors / blockers carried in `details`, if any. */
  get detailLines(): string[] {
    const d = this.details as unknown;
    if (Array.isArray(d)) {
      return d.map((x) => (typeof x === "object" && x && "message" in x ? `${(x as { field?: string }).field ? `${(x as { field: string }).field}: ` : ""}${(x as { message: string }).message}` : String(x)));
    }
    if (d && typeof d === "object") {
      const obj = d as Record<string, unknown>;
      if (Array.isArray(obj.blockers)) return obj.blockers.map(String);
      if (typeof obj.eligibility === "string") return [obj.eligibility];
      if (Array.isArray(obj.allowed)) return [`Allowed next statuses: ${obj.allowed.join(", ") || "none"}`];
    }
    return [];
  }
}

async function parse(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Check that the backend is running.");
  }
  const data = await parse(res);
  if (!res.ok) {
    const err = (data as { error?: { code: string; message: string; details?: unknown; request_id?: string } })?.error;
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/login")) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status}).`, err?.details, err?.request_id);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
};

export const fetcher = <T,>(path: string) => api.get<T>(path);
