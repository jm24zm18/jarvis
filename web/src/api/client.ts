import { useAuthStore } from "../stores/auth";

async function readErrorMessage(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) return "";
  try {
    const data = JSON.parse(text) as { detail?: unknown; message?: unknown };
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail;
    if (typeof data.message === "string" && data.message.trim()) return data.message;
  } catch {
    // Non-JSON response body; return raw text.
  }
  return text;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useAuthStore.getState().token;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Content-Type") && init.body) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    const isLoginEndpoint = path === "/api/v1/auth/login";
    if (!isLoginEndpoint) useAuthStore.getState().clearAuth();
    const message = await readErrorMessage(response);
    throw new Error(message || (isLoginEndpoint ? "Invalid credentials" : "Session expired"));
  }
  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}
