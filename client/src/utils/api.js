const STORAGE_KEY = "freeroll_backend_url";

export function getBackendUrl() {
  return localStorage.getItem(STORAGE_KEY) || "http://localhost:8000";
}

export function setBackendUrl(url) {
  localStorage.setItem(STORAGE_KEY, url);
}

export async function api(path, options = {}) {
  const base = getBackendUrl();
  const url = `${base}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}
