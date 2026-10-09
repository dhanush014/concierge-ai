import { createClient } from "@/lib/supabase/browser";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * An error from the FastAPI backend. `detail` is its error code, e.g. "slot_not_open".
 * status 0 means no response at all (network failure).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = "ApiError";
  }
}

function errorDetail(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
    return body.detail;
  }
  return fallback;
}

/**
 * Call the FastAPI backend from a Client Component. Adds the signed-in user's
 * Supabase access token as `Authorization: Bearer ...` and sends/receives JSON.
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await createClient().auth.getSession();
  const token = data.session?.access_token;

  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // JSON for string bodies. FormData (file uploads) sets its own multipart header.
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let resp: Response;
  try {
    resp = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    // Server down, offline, or CORS failure. Status 0 = "no response".
    throw new ApiError(0, "network");
  }
  if (!resp.ok) {
    const body: unknown = await resp.json().catch(() => null);
    throw new ApiError(resp.status, errorDetail(body, resp.statusText));
  }
  if (resp.status === 204) return undefined as T; // No Content (e.g. DELETE)
  return (await resp.json()) as T;
}

/** 500s and network failures: worth a Retry button. */
export function isRetryable(error: unknown): boolean {
  return !(error instanceof ApiError) || error.status === 0 || error.status >= 500;
}

export function isStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError && error.status === status;
}
