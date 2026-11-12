/** Negocjacje ekspresu: lista oraz szczegóły z pipeline'em, akcjami i historią. */
import { api } from "../api.js";
import { POLL_MS } from "../config.js";
import { COLORS, createMap, drawPackages, drawRoute, fitTo, legend } from "../map.js";
import { session } from "../session.js";
import { $, emptyState, esc, fmtDate, money, readForm, spinner, stageBadge, toast, withBusy } from "../ui.js";

// ------------------------------------------------------------------ lista
export async function negotiationListView(root) {
  root.innerHTML = spinner();
  const negs = await api.get("/negotiations/");
  const open = negs.filter((n) => n.is_open), closed = negs.filter((n) => !n.is_open);
  const row = (n) => `
    <a href="#/negotiations/${n.id}" class="list-group-item list-group-item-action">
      <div class="d-flex justify-content-between align-items-center">
        <div><b>${esc(n.package.code)}</b> <span class="text-muted small">#${n.id}</span>
          ${n.my_turn ? '<span class="badge text-bg-danger ms-1">Twój ruch</span>' : ""}
          <div class="small text-muted">${esc(n.sender.name)} → ${esc(n.recipient.name)} · kierowca ${esc(n.driver.name)}</div></div>
        <div class="text-end"><div class="fw-semibold">${money(n.amount)}</div>${stageBadge(n)}</div>
      </div>
    </a>`;
  root.innerHTML = `
    <h3>${session.isDriver ? "Zlecenia ekspresowe" : "Negocjacje ekspresu"}</h3>
    <p class="text-muted small">${session.isDriver
      ? "Nadawca i odbiorca uzgodnili cenę – zdecyduj, czy dorzucasz paczkę do swojej trasy."
      : "Negocjacje dorzucenia paczki do trasy kierowcy, który już jeździ. Ekspres zamówisz w szczegółach paczki."}</p>
    <div class="row g-4">
      <div class="col-lg-6"><h6>W toku (${open.length})</h6>
        <div class="list-group">${open.map(row).join("") || `<div class="list-group-item">${emptyState("Brak otwartych negocjacji.")}</div>`}</div></div>
      <div class="col-lg-6"><h6>Zakończone (${closed.length})</h6>
        <div class="list-group">${closed.map(row).join("") || `<div class="list-group-item">${emptyState("Jeszcze nic.")}</div>`}</div></div>
    </div>`;
}

// ------------------------------------------------------------------ szczegóły
function stepsBar(steps) {
  return `<div class="d-flex flex-wrap gap-2 mb-4">${steps.map((s, i) => `
    <div class="step text-center p-2 rounded border small ${s.current ? "border-primary bg-primary-subtle fw-semibold"
      : s.reached ? "bg-success-subtle border-success-subtle" : "text-muted bg-white"}">
      ${i + 1}. ${esc(s.label)}${s.reached && !s.current ? " (gotowe)" : ""}</div>`).join("")}</div>`;
}

function termsCard(n) {
  const ok = (v) => (v ? " – zgoda" : "");
  return `<div class="card p-3 mb-3">
    <div class="d-flex justify-content-between">
      <div><div class="small text-muted">Aktualna kwota dla kierowcy</div><div class="display-6 fw-semibold">${money(n.amount)}</div></div>
      <div class="text-end small"><div class="text-muted">Cena algorytmu</div><div class="fs-5">${money(n.quoted_amount)}</div>
        <div class="text-muted">objazd +${n.quote.detour_km} km / +${Math.round(n.quote.detour_min)} min</div></div>
    </div>
    <div class="d-flex justify-content-between small">
      <span><b>${esc(n.sender.name)}</b> (nadawca): ${money(n.sender_amount)}${ok(n.sender_ok)}</span>
      <span><b>${esc(n.recipient.name)}</b> (odbiorca): ${money(n.recipient_amount)}${ok(n.recipient_ok)}</span>
    </div>
    <div class="small text-muted mt-2">Kierowca: <b>${esc(n.driver.name)}</b> ${esc(n.driver.phone || "")}
      · ${esc(n.driver.vehicle_name || "")}</div>
    ${n.stage === "parties" ? `<div class="small mt-1">Kontroferty: ${n.party_rounds} / ${n.max_party_rounds}</div>` : ""}
  </div>`;
}

function liveQuoteBox(q) {
  if (!q) return "";
  return `<div class="alert ${q.feasible ? "alert-info" : "alert-warning"} small"><b>Aktualny koszt objazdu dla Ciebie:</b>
    ${q.feasible ? `+${q.detour_km} km, +${Math.round(q.detour_min)} min → algorytm wycenia teraz na <b>${money(q.amount)}</b>.`
      : `${esc(q.reason)} Możesz mimo to zaakceptować – trasa zostanie przeplanowana.`}</div>`;
}

function actionsCard(n) {
  if (!n.actions.length) {
    return n.is_open ? '<div class="alert alert-light small">Czekamy na drugą stronę – nie masz teraz żadnej akcji.</div>' : "";
  }
  const withAmount = n.actions.filter((a) => a.with_amount);
  const simple = n.actions.filter((a) => !a.with_amount);
  const roleLabel = { sender: "nadawca", recipient: "odbiorca", driver: "kierowca" }[n.my_role];
  return `<div class="card p-3 mb-3 border-primary">
    <h6 class="mb-2">Twoja decyzja (${roleLabel})</h6>
    ${withAmount.map((a) => `
      <form class="border rounded p-2 mb-2" data-action="${a.action}" novalidate>
        <div class="row g-2 align-items-end">
          <div class="col"><label class="form-label small mb-0">Kwota [zł]</label>
            <input name="amount" data-type="number" class="form-control" inputmode="decimal" value="${esc(n.amount)}"></div>
          ${a.with_share ? `<div class="col"><label class="form-label small mb-0">Nadawca płaci [%]</label>
            <input name="sender_share_pct" data-type="number" type="number" min="0" max="100" class="form-control" value="${n.sender_share_pct}"></div>` : ""}
        </div>
        <input name="note" class="form-control form-control-sm mt-2" maxlength="300" placeholder="Komentarz (opcjonalnie)">
        <button class="btn btn-${a.style} btn-sm mt-2 w-100">${esc(a.label)}</button>
      </form>`).join("")}
    ${simple.length ? `<form data-simple novalidate>
      <input name="note" class="form-control form-control-sm mb-2" maxlength="300" placeholder="Komentarz (opcjonalnie)">
      <div class="d-flex flex-wrap gap-2">${simple.map((a) =>
        `<button type="button" data-action="${a.action}" class="btn btn-${a.style} flex-fill">${esc(a.label)}</button>`).join("")}</div>
    </form>` : ""}
  </div>`;
}

function historyCard(events) {
  return `<div class="card p-3"><h6>Historia</h6><ul class="timeline small">${events.map((e) => `
    <li class="ok"><span class="text-muted">${fmtDate(e.created_at)}</span>
      <b>${esc(e.role_label)}</b>${e.actor ? ` (${esc(e.actor)})` : ""}: ${esc(e.action_label)}
      ${e.amount ? ` · ${money(e.amount)}` : ""}${e.sender_share_pct !== null ? ` · nadawca ${e.sender_share_pct}%` : ""}
      ${e.note ? `<div class="fst-italic">„${esc(e.note)}”</div>` : ""}</li>`).join("")}</ul></div>`;
}

export async function negotiationDetailView(root, { id }) {
  root.innerHTML = spinner();
  let map = null, timer = null, lastUpdate = null;

  const draw = (n) => {
    lastUpdate = n.updated_at;
    if (map) { map.remove(); map = null; }
    root.innerHTML = `
      <div class="d-flex justify-content-between align-items-center mb-2">
        <h3 class="mb-0">Ekspres ${esc(n.package.code)} <small class="text-muted fs-6">negocjacja #${n.id}</small></h3>
        <span class="fs-6">${stageBadge(n)}</span></div>
      ${stepsBar(n.steps)}
      <div class="row g-4">
        <div class="col-lg-5">${termsCard(n)}${liveQuoteBox(n.live_quote)}${actionsCard(n)}${historyCard(n.events)}</div>
        <div class="col-lg-7">
          <div class="card p-3 mb-3 small">
            <div>${esc(n.package.pickup.address)}</div>
            <div>${esc(n.package.delivery.address)}</div>
            <div class="text-muted">${esc(n.package.description || "paczka")}, ${n.package.weight_kg} kg</div>
            ${session.isParty ? `<a href="#/packages/${n.package.id}">Szczegóły paczki</a>` : ""}
          </div>
          <div id="map" class="tx-map"></div>${legend()}
          <div class="small text-muted">${n.driver_route ? "Fioletowa linia: pozostała część trasy kierowcy. " : ""}Pomarańczowa: paczka ekspresowa.</div>
        </div>
      </div>`;

    map = createMap($("#map", root));
    drawPackages(map, [{ ...n.package }], { color: COLORS.express, fit: false });
    if (n.driver_route) drawRoute(map, n.driver_route);
    else fitTo(map, [[n.package.pickup.lat, n.package.pickup.lng], [n.package.delivery.lat, n.package.delivery.lng]]);
    bindActions(n);
  };

  const perform = async (button, payload) => {
    try {
      const res = await withBusy(button, () => api.post(`/negotiations/${id}/actions/`, payload));
      toast(res.message);
      draw(res.negotiation);
      session.load().catch(() => {});   // licznik w menu
    } catch (err) {
      toast(err.message, "danger");
    }
  };

  const bindActions = () => {
    root.querySelectorAll("form[data-action]").forEach((form) => form.addEventListener("submit", (e) => {
      e.preventDefault();
      perform($("button", form), { action: form.dataset.action, ...readForm(form) });
    }));
    const simple = $("form[data-simple]", root);
    simple?.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const action = b.dataset.action;
      if (["reject", "cancel"].includes(action) && !confirm("Na pewno? Negocjacja zostanie zakończona.")) return;
      perform(b, { action, note: simple.note.value.trim() });
    }));
  };

  draw(await api.get(`/negotiations/${id}/`));

  // druga strona mogła odpowiedzieć – odśwież, jeśli nic nie wpisujesz
  timer = setInterval(async () => {
    if (document.visibilityState !== "visible") return;
    const active = document.activeElement;
    if (active && root.contains(active) && ["INPUT", "TEXTAREA"].includes(active.tagName)) return;
    try {
      const n = await api.get(`/negotiations/${id}/`);
      if (n.updated_at !== lastUpdate) draw(n);
    } catch { /* chwilowy brak sieci */ }
  }, POLL_MS);

  return () => { clearInterval(timer); if (map) map.remove(); };
}
