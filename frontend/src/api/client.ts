export const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  code: string;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    const d = detail as { message?: string; code?: string } | string | undefined;
    const message =
      typeof d === 'string' ? d : d && typeof d === 'object' && d.message ? d.message : JSON.stringify(detail);
    super(message);
    this.status = status;
    this.code = typeof d === 'object' && d && d.code ? d.code : String(status);
    this.detail = detail;
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const opts: RequestInit = { ...rest };
  if (json !== undefined) {
    opts.body = JSON.stringify(json);
    opts.headers = { 'Content-Type': 'application/json', ...(rest.headers ?? {}) };
  }
  const res = await fetch(API_BASE + path, opts);
  const text = await res.text();
  let body: unknown = undefined;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = text;
  }
  if (!res.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : body;
    throw new ApiError(res.status, detail);
  }
  return body as T;
}

export const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));
