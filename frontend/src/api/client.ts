function _authHeaders(): Record<string, string> {
  const token = localStorage.getItem("jarvis_auth_token") || "";
  return token ? { "Authorization": `Bearer ${token}` } : {};
}

export async function apiGet<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: _authHeaders() });
  if (!res.ok) throw new Error(`API request failed: ${res.status}`);
  return res.json();
}

export async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ..._authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(error.error || `API request failed: ${res.status}`);
  }
  return res.json();
}
