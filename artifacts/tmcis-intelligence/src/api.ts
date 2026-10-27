export const API_BASE = "/api/api/v1";

type RequestOptions = {
  method?: string;
  body?: unknown;
  file?: File;
  headers?: Record<string, string>;
};

function csrfToken() {
  const pair = document.cookie.split("; ").find((item) => item.startsWith("csrftoken="));
  return pair ? decodeURIComponent(pair.split("=")[1] ?? "") : "";
}

export async function api<T = any>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? (options.body || options.file ? "POST" : "GET");
  const headers: Record<string, string> = { ...options.headers };
  const token = csrfToken();
  if (token && !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
    headers["X-CSRFToken"] = token;
  }

  let body: BodyInit | undefined;
  if (options.file) {
    body = new FormData();
    body.append("file", options.file);
    if (options.body && typeof options.body === "object") {
      Object.entries(options.body as Record<string, unknown>).forEach(([key, value]) => {
        (body as FormData).append(key, String(value));
      });
    }
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers,
    body,
  });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload
        ? payload.error ?? payload.detail ?? Object.values(payload).flat().join(" ")
        : payload;
    throw new Error(String(message || `Request failed (${response.status}).`));
  }
  return payload as T;
}

export function rows<T>(payload: any): T[] {
  return Array.isArray(payload) ? payload : payload?.results ?? [];
}
