const API = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export const TOKEN_KEY = "packsure_access_token";

export function logout() {
  localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event("packsure-logout"));
}

export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers);
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path.startsWith("http") ? path : `${API}${path}`, { ...options, headers });
  if (response.status === 401 && !path.endsWith("/auth/login")) logout();
  return response;
}

export async function apiJson(path, options = {}) {
  const response = await apiFetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed. Please try again.");
  return data;
}

export function apiDate(value) {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
}
