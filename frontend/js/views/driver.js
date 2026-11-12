/**
 * Panel kierowcy: wyznaczanie trasy z punktów paczek.
 *  - start: baza z profilu / ostatni przystanek albo punkt kliknięty na mapie,
 *  - algorytm dobiera paczki z puli i układa kolejność (odbiór przed doręczeniem, ładowność, czas zmiany),
 *  - lista przystanków z „Odebrano” / „Doręczono”.
 */
import { api } from "../api.js";
import { createMap, drawPackages, drawRoute, fitTo, legend, pinIcon, reverseGeocode } from "../map.js";
import { session } from "../session.js";
import { $, emptyState, esc, fmtDate, money, readForm, showErrors, spinner, toast, withBusy } from "../ui.js";

function stopItem(s, isNext) {
  const p = s.package;
  const action = s.kind === "P" ? "Odebrano" : "Doręczono";
  return `<div class="list-group-item stop-item ${s.done ? "done" : ""} ${isNext ? "next" : ""}" data-stop="${s.id}">
    <div class="d-flex justify-content-between align-items-start gap-2">
      <div>
        <div class="stop-kind ${s.kind === "P" ? "text-primary" : "text-success"}">${s.order}. ${esc(s.kind_label)}
          · ${esc(p.code)}${p.price ? ` · <span class="text-warning-emphasis">ekspres ${money(p.price)}</span>` : ""}</div>
        <div>${esc(s.address)}</div>
        <div class="small text-muted">${esc(p.description || "paczka")}, ${p.weight_kg} kg
          ${p.person ? ` · ${esc(p.person.name)} ${esc(p.person.phone || "")}` : ""}${p.contact ? ` · ${esc(p.contact)}` : ""}</div>
        ${p.notes ? `<div class="small fst-italic">${esc(p.notes)}</div>` : ""}
      </div>
      <div class="text-end text-nowrap">
        <div class="small text-muted">${s.done ? "wykonano " + fmtDate(s.completed_at, { date: false }) : "ok. " + fmtDate(s.eta, { date: false })}</div>
        ${s.done ? "" : `<button class="btn btn-sm ${isNext ? "btn-primary" : "btn-outline-secondary"} mt-1" data-complete="${s.id}">${action}</button>`}
      </div>
    </div>
  </div>`;
}

export async function driverView(root) {
  root.innerHTML = spinner();
  let [summary, pool] = await Promise.all([api.get("/driver/route/"), api.get("/driver/pool/")]);
  const me = session.user;
  let startPoint = null;          // kliknięty na mapie start (nadpisuje bazę)
  let startMarker = null;

  root.innerHTML = `
    <div class="row g-4">
      <div class="col-xl-5">
        <div data-alerts></div>
        <div class="card p-3 mb-3">
          <h5 class="mb-1">Wyznacz trasę</h5>
          <div class="small text-muted mb-3">Algorytm wybierze paczki, które opłaca się wziąć po drodze, i ułoży kolejność
            przystanków: każdy odbiór przed doręczeniem, bez przekroczenia ładowności i czasu pracy. Paczki już przypisane zostają w trasie.</div>
          <form novalidate>
            <div class="form-error"></div>
            <div class="mb-2 small"><b>Start:</b> <span data-start-label></span>
              <button type="button" class="btn btn-link btn-sm p-0 ms-1 d-none" data-start-reset>użyj domyślnego</button>
              <div class="text-muted">Kliknij na mapie, żeby ustawić inny punkt startu.</div></div>
            <div class="row g-2">
              <div class="col-4"><label class="form-label small mb-0">Ładowność</label>
                <div class="input-group input-group-sm"><input name="capacity_kg" data-type="number" class="form-control" value="${me.vehicle_capacity_kg}">
                <span class="input-group-text">kg</span></div></div>
              <div class="col-4"><label class="form-label small mb-0">Czas pracy</label>
                <div class="input-group input-group-sm"><input name="shift_hours" data-type="number" class="form-control"
                  value="${summary.remaining_shift_h ?? 8}"><span class="input-group-text">h</span></div></div>
              <div class="col-4"><label class="form-label small mb-0">Maks. nowych</label>
                <input name="max_new" data-type="number" class="form-control form-control-sm" placeholder="bez limitu"></div>
            </div>
            <div class="form-check mt-2"><input class="form-check-input" type="checkbox" name="take_new" id="take_new" checked>
              <label class="form-check-label small" for="take_new">Dobierz nowe paczki z puli (<span data-pool-count>${pool.length}</span> czeka)</label></div>
            <button class="btn btn-primary w-100 mt-3"><span data-plan-label></span></button>
          </form>
        </div>
        <div data-route></div>
      </div>
      <div class="col-xl-7">
        <div class="d-flex justify-content-end mb-1"><div class="form-check form-switch small">
          <input class="form-check-input" type="checkbox" id="show-pool" checked>
          <label class="form-check-label" for="show-pool">pokaż wolne paczki (szare)</label></div></div>
        <div id="map" class="tx-map tx-map-tall"></div>${legend()}
      </div>
    </div>`;

  const form = $("form", root);
  const map = createMap($("#map", root));
  const routeLayer = L.layerGroup().addTo(map);
  const poolLayer = L.layerGroup().addTo(map);

  const defaultStart = () => {
    const r = summary.route;
    if (r) {
      const last = [...r.stops].reverse().find((s) => s.done);
      return last ? { label: `ostatni przystanek – ${last.address}`, ...last } : { label: "start obecnej trasy", ...r.start };
    }
    return summary.base ? { label: `baza – ${summary.base.address}`, ...summary.base } : null;
  };

  const renderStart = () => {
    const def = defaultStart();
    const label = startPoint ? `wskazany na mapie – ${startPoint.address}`
      : def ? def.label : '<span class="text-danger">brak – ustaw bazę w <a href="#/account">profilu</a> albo kliknij na mapie</span>';
    $("[data-start-label]", root).innerHTML = startPoint ? esc(label) : (def ? esc(label) : label);
    $("[data-start-reset]", root).classList.toggle("d-none", !startPoint);
    if (startMarker) { startMarker.remove(); startMarker = null; }
    const p = startPoint || (!summary.route && def);
    if (p) startMarker = L.marker([p.lat, p.lng], { icon: pinIcon("start", "S"), zIndexOffset: 500 })
      .bindPopup("Start planowania").addTo(map);
  };

  const renderPool = () => {
    poolLayer.clearLayers();
    if ($("#show-pool", root).checked) drawPackages(map, pool, { fit: false, layer: poolLayer });
    $("[data-pool-count]", root).textContent = pool.length;
  };

  const renderRoute = () => {
    const r = summary.route;
    $("[data-plan-label]", root).textContent = r ? "Przelicz trasę" : "Wyznacz trasę";
    routeLayer.clearLayers();
    const box = $("[data-route]", root);
    if (!r) {
      box.innerHTML = `<div class="card">${emptyState("Nie masz aktywnej trasy. Ustaw parametry i kliknij „Wyznacz trasę”.")}</div>`;
      const pts = [...pool.flatMap((p) => [[p.pickup.lat, p.pickup.lng], [p.delivery.lat, p.delivery.lng]])];
      if (summary.base) pts.push([summary.base.lat, summary.base.lng]);
      fitTo(map, pts);
      return;
    }
    drawRoute(map, r, { layer: routeLayer, onStopClick: (s) => {
      const el = box.querySelector(`[data-stop="${s.id}"]`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    } });
    const next = r.stops.find((s) => !s.done);
    box.innerHTML = `
      <div class="card">
        <div class="card-header bg-white">
          <div class="d-flex justify-content-between align-items-center">
            <b>Trasa #${r.id}</b>
            <span class="small text-muted">${r.done_count}/${r.stops.length} przystanków</span></div>
          <div class="row text-center small mt-2 g-0">
            <div class="col"><div class="fs-5 fw-semibold">${r.distance_km}</div>km</div>
            <div class="col"><div class="fs-5 fw-semibold">${r.duration_min}</div>min</div>
            <div class="col"><div class="fs-5 fw-semibold">${summary.onboard_count}</div>w aucie</div>
            <div class="col"><div class="fs-5 fw-semibold">${summary.onboard_weight_kg}</div>kg / ${summary.capacity_kg}</div>
          </div>
          ${r.matrix_source !== "osrm" ? '<div class="small text-warning-emphasis mt-1">Serwer tras niedostępny – czasy szacunkowe.</div>' : ""}
          ${next ? `<a class="btn btn-outline-primary btn-sm w-100 mt-2" target="_blank" rel="noopener"
            href="https://www.google.com/maps/dir/?api=1&destination=${next.lat},${next.lng}">Nawiguj do: ${esc(next.address)}</a>` : ""}
        </div>
        <div class="list-group list-group-flush stop-list">${r.stops.map((s) => stopItem(s, s === next)).join("")}</div>
      </div>`;
    box.querySelectorAll("[data-complete]").forEach((b) => b.addEventListener("click", async () => {
      try {
        const res = await withBusy(b, () => api.post(`/driver/stops/${b.dataset.complete}/complete/`));
        toast(res.message);
        summary = res;
        renderAll();
      } catch (err) {
        toast(err.message, "danger");
      }
    }));
  };

  const renderAlerts = () => {
    const n = session.user.pending_negotiations;
    $("[data-alerts]", root).innerHTML = n ? `<div class="alert alert-primary d-flex justify-content-between align-items-center">
      <span>${n} zleceni${n === 1 ? "e ekspresowe czeka" : "a ekspresowe czekają"} na Twoją decyzję.</span>
      <a class="btn btn-primary btn-sm" href="#/negotiations">Zobacz</a></div>` : "";
  };

  const renderAll = () => { renderRoute(); renderPool(); renderStart(); renderAlerts(); };
  renderAll();

  map.on("click", async (e) => {
    startPoint = { lat: e.latlng.lat, lng: e.latlng.lng, address: "szukam adresu…" };
    renderStart();
    startPoint.address = await reverseGeocode(e.latlng.lat, e.latlng.lng);
    renderStart();
  });
  $("[data-start-reset]", root).addEventListener("click", () => { startPoint = null; renderStart(); });
  $("#show-pool", root).addEventListener("change", renderPool);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = readForm(form);
    if (startPoint) Object.assign(data, { start_lat: startPoint.lat, start_lng: startPoint.lng });
    try {
      const res = await withBusy($("button.btn-primary", form), () => api.post("/driver/route/", data));
      summary = res;
      pool = await api.get("/driver/pool/");
      startPoint = null;
      res.messages.forEach((m) => toast(m, "warning"));
      if (res.route) toast(`Trasa: ${res.route.stops.length} przystanków, ${res.route.distance_km} km, ok. ${res.route.duration_min} min. Nowe paczki: ${res.new_packages}.`);
      renderAll();
    } catch (err) {
      showErrors(form, err);
    }
  });

  session.onChange(renderAlerts);   // licznik zleceń odświeża app.js w tle
  return () => { session.offChange(renderAlerts); map.remove(); };
}
