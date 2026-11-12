/** Drobne helpery interfejsu: escape HTML, formatowanie, toasty, obsługa formularzy. */

const ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ENTITIES[c]);

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function money(v) {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("pl-PL", { style: "currency", currency: "PLN" });
}

export function fmtDate(iso, { time = true, date = true } = {}) {
  if (!iso) return "—";
  const opts = {};
  if (date) Object.assign(opts, { day: "2-digit", month: "2-digit" });
  if (time) Object.assign(opts, { hour: "2-digit", minute: "2-digit" });
  return new Date(iso).toLocaleString("pl-PL", opts);
}

export const STATUS_BADGE = {
  new: "secondary", negotiating: "primary", assigned: "info",
  picked_up: "warning", delivered: "success", cancelled: "dark",
};

export const STATUS_OPTIONS = [
  ["new", "Oczekuje na kuriera"], ["negotiating", "Negocjacja ekspresu"], ["assigned", "Przypisana do trasy"],
  ["picked_up", "W drodze"], ["delivered", "Doręczona"], ["cancelled", "Anulowana"],
];

export const statusBadge = (status, label) =>
  `<span class="badge text-bg-${STATUS_BADGE[status] || "secondary"}">${esc(label)}</span>`;

export function stageBadge(neg) {
  const cls = neg.stage === "accepted" ? "success" : neg.is_open ? "primary" : "secondary";
  return `<span class="badge text-bg-${cls}">${esc(neg.stage_label)}</span>`;
}

export const spinner = (text = "Ładowanie…") => `<div class="empty">${esc(text)}</div>`;

export const emptyState = (text) => `<div class="empty">${text}</div>`;

export const errorBox = (e) =>
  `<div class="alert alert-danger">${esc(e.message || e)}</div>`;

export function toast(message, type = "success") {
  const el = document.createElement("div");
  el.className = `toast align-items-center text-bg-${type} border-0`;
  el.setAttribute("role", "status");
  el.innerHTML = `<div class="d-flex"><div class="toast-body">${esc(message)}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>`;
  $("#toasts").appendChild(el);
  const t = new bootstrap.Toast(el, { delay: type === "danger" ? 7000 : 4000 });
  el.addEventListener("hidden.bs.toast", () => el.remove());
  t.show();
}

/**
 * Odczyt formularza do obiektu. Pola z data-type="number" → liczba albo null,
 * checkboxy → true/false, puste pola tekstowe → "".
 */
export function readForm(form) {
  const data = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") data[el.name] = el.checked;
    else if (el.type === "radio") { if (el.checked) data[el.name] = el.value; }
    else if (el.dataset.type === "number") data[el.name] = el.value === "" ? null : Number(el.value.replace(",", "."));
    else data[el.name] = el.value.trim();
  }
  return data;
}

export function clearErrors(form) {
  $$(".is-invalid", form).forEach((el) => el.classList.remove("is-invalid"));
  $$(".invalid-feedback.api", form).forEach((el) => el.remove());
  const box = $(".form-error", form);
  if (box) box.innerHTML = "";
}

/** Błędy z API ({errors: {pole: [...]}}) przy odpowiednich polach + komunikat ogólny. */
export function showErrors(form, err) {
  clearErrors(form);
  const unplaced = [];
  Object.entries(err.errors || {}).forEach(([field, msgs]) => {
    const input = form.elements[field];
    const el = input instanceof RadioNodeList ? input[0] : input;
    if (!el || el.type === "hidden") {
      unplaced.push(...msgs);
      return;
    }
    el.classList.add("is-invalid");
    const fb = document.createElement("div");
    fb.className = "invalid-feedback api";
    fb.textContent = msgs.join(" ");
    (el.closest(".input-group") || el).after(fb);
  });
  const box = $(".form-error", form);
  const text = [err.message, ...unplaced].filter(Boolean).join(" ");
  if (box) box.innerHTML = `<div class="alert alert-danger py-2 small mb-2">${esc(text)}</div>`;
  else toast(text, "danger");
}

/** Blokuje przycisk na czas zapytania; zwraca wynik funkcji. */
export async function withBusy(button, fn) {
  const html = button?.innerHTML;
  if (button) {
    button.disabled = true;
    button.textContent = "Chwila…";
  }
  try {
    return await fn();
  } finally {
    if (button) {
      button.disabled = false;
      button.innerHTML = html;
    }
  }
}

export function navigate(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = hash;
}
