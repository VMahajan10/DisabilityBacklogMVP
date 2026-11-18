export class ApiError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(msg);
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  get: <T,>(p: string) => req<T>(p),
  post: <T,>(p: string, body?: unknown) => req<T>(p, json("POST", body)),
  put: <T,>(p: string, body?: unknown) => req<T>(p, json("PUT", body)),
  upload: <T,>(p: string, files: FileList | File[]) => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    return req<T>(p, { method: "POST", body: fd });
  },
  logEvent: (claimId: number, event_type: string, payload: Record<string, unknown>) =>
    req(`/api/claims/${claimId}/events`, json("POST", { event_type, payload })).catch(() => undefined),
};
