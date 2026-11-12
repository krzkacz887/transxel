/**
 * Klient REST API. Jedyne miejsce, które zna adres backendu i format błędów.
 * Token logowania trzymamy w localStorage i wysyłamy w nagłówku Authorization.
 */
import { API_URL } from "./config.js";

const TOKEN_KEY = "transxel.token";

let token = localStorage.getItem(TOKEN_KEY);
let onUnauthorized = () => {};

export function setToken(value) {
  token = value || null;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export const hasToken = () => Boolean(token);
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export class ApiError extends Error {
  constructor(status, message, errors) {
    super(message);
    this.status = status;
    this.errors = errors || {};
  }
}

async function request(method, path, { body, query } = {}) {
  const url = new URL(API_URL + path);
  Object.entries(query || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  });
  const headers = { Accept: "application/json" };
  if (token) headers.Authorization = `Token ${token}`;
  const init = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, `Brak połączenia z API (${API_URL}). Czy backend jest uruchomiony?`);
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* pusta lub nie-JSON odpowiedź */ }

  if (!res.ok) {
    const err = new ApiError(res.status, data?.error || `Błąd serwera (${res.status})`, data?.errors);
    if (res.status === 401 && token) {
      setToken(null);
      onUnauthorized(err);
    }
    throw err;
  }
  return data;
}

export const api = {
  get: (path, query) => request("GET", path, { query }),
  post: (path, body = {}) => request("POST", path, { body }),
  patch: (path, body) => request("PATCH", path, { body }),
  del: (path) => request("DELETE", path),
};
