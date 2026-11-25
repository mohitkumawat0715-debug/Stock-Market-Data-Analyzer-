import type { ApiProblem } from "@/lib/types";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api/v1")
  .trim()
  .replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  details: Record<string, unknown>;

  constructor(message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_BASE + path, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError(
      "The API cannot be reached. Start the FastAPI backend at http://127.0.0.1:8000.",
      0,
    );
  }

  const body = response.status === 204 ? undefined : await response.json().catch(() => undefined);
  if (!response.ok) {
    const problem = (body || {}) as ApiProblem;
    const detailText = problem.details && Object.keys(problem.details).length
      ? " " + JSON.stringify(problem.details)
      : "";
    throw new ApiError(
      (problem.message || "The request could not be completed.") + detailText,
      response.status,
      problem.details || {},
    );
  }
  return body as T;
}

export function query(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const result = params.toString();
  return result ? "?" + result : "";
}

export function post<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(data) });
}

export function patch<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
}

export function remove(path: string): Promise<void> {
  return api<void>(path, { method: "DELETE" });
}
