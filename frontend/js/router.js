/**
 * Prosty router na hashu. Każdy widok to funkcja async (root, params) → [cleanup].
 * Cleanup (np. usunięcie mapy, zatrzymanie odświeżania) wołamy przy przejściu do innego widoku.
 */
import { session } from "./session.js";
import { errorBox, esc } from "./ui.js";

const routes = [];
let cleanup = null;

export function route(pattern, view, guard = "user") {
  const keys = [];
  const regex = new RegExp("^" + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return "([^/]+)"; }) + "/?$");
  routes.push({ regex, keys, view, guard });
}

function allowed(guard) {
  const u = session.user;
  switch (guard) {
    case "public": return true;
    case "guest": return !u;
    case "party": return u && u.role !== "driver";
    case "driver": return u?.role === "driver";
    default: return Boolean(u);
  }
}

export async function render() {
  const [path, qs = ""] = (location.hash.replace(/^#/, "") || "/").split("?");
  const root = document.getElementById("app");
  if (cleanup) { cleanup(); cleanup = null; }

  const match = routes.map((r) => ({ r, m: path.match(r.regex) })).find((x) => x.m);
  if (!match) {
    location.hash = session.homePath();
    return;
  }
  const { r, m } = match;
  if (!allowed(r.guard)) {
    location.hash = session.user ? session.homePath() : `#/login?next=${encodeURIComponent(path)}`;
    return;
  }
  const params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])]));
  params.query = new URLSearchParams(qs);
  window.scrollTo(0, 0);
  document.querySelectorAll("#nav-links .nav-link").forEach((a) =>
    a.classList.toggle("active", path.startsWith(a.getAttribute("href").slice(1).split("?")[0])));

  try {
    const result = await r.view(root, params);
    cleanup = typeof result === "function" ? result : null;
  } catch (e) {
    root.innerHTML = errorBox(e) + `<a href="${esc(session.homePath())}">Wróć</a>`;
  }
}

export function start() {
  window.addEventListener("hashchange", render);
  render();
}
