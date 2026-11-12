/** Etap 1 ekspresu: wyceny kierowców w trasie i start negocjacji. */
import { api } from "../api.js";
import { COLORS, createMap, drawPackages, drawRoute, legend } from "../map.js";
import { session } from "../session.js";
import { $, emptyState, esc, money, navigate, readForm, showErrors, spinner, toast, withBusy } from "../ui.js";

export async function expressView(root, { id }) {
  root.innerHTML = spinner("Liczę objazdy kierowców w trasie…");
  const pkg = await api.get(`/packages/${id}/`);
  if (!pkg.can_express) {
    toast("Ta paczka nie czeka już w puli – ekspres jest niedostępny.", "warning");
    navigate(`#/packages/${id}`);
    return;
  }
  const quotes = await api.get(`/packages/${id}/quotes/`);
  const feasible = quotes.filter((q) => q.feasible);
  const isSender = session.user.role === "sender";

  root.innerHTML = `
    <div class="mb-3"><a href="#/packages/${pkg.id}" class="small">${esc(pkg.code)}</a>
      <h3 class="mb-0">Ekspres – dorzuć paczkę do trwającej trasy</h3>
      <div class="text-muted small">Cena wynika z objazdu: ile kilometrów i minut dołoży kierowcy wstawienie Twojej paczki
        w najlepsze miejsce jego trasy (kolejność jego przystanków się nie zmienia).</div></div>
    <div class="row g-4">
      <div class="col-lg-5">
        ${quotes.length ? quotes.map((q, i) => `
          <label class="card p-3 mb-2 quote ${q.feasible ? "" : "opacity-50"}" style="cursor:${q.feasible ? "pointer" : "default"}">
            <div class="d-flex gap-3 align-items-start">
              <input type="radio" class="form-check-input mt-1" name="quote" value="${i}" ${q.feasible ? "" : "disabled"}
                ${q === feasible[0] ? "checked" : ""}>
              <div class="flex-fill">
                <div class="d-flex justify-content-between"><b>${esc(q.driver.name)}</b>
                  <span class="fs-5 fw-semibold">${q.feasible ? money(q.amount) : ""}</span></div>
                <div class="small text-muted">${esc(q.driver.vehicle_name || "pojazd")} · ładowność ${q.driver.vehicle_capacity_kg} kg</div>
                ${q.feasible ? `<div class="small">objazd +${q.detour_km} km / +${Math.round(q.detour_min)} min
                    ${q.source !== "osrm" ? '<span class="badge text-bg-warning">szacunek</span>' : ""}</div>
                  <details class="small mt-1"><summary>Jak policzono cenę</summary>
                    <table class="table table-sm mb-0">${q.breakdown.map((b) =>
                      `<tr><td>${esc(b.label)}</td><td class="text-end">${money(b.value)}</td></tr>`).join("")}</table></details>`
                  : `<div class="small text-danger">${esc(q.reason)}</div>`}
              </div>
            </div>
          </label>`).join("") : emptyState("Żaden kierowca nie jest teraz w trasie. Paczka poczeka w zwykłej puli.")}

        ${feasible.length ? `<form class="card p-3 mt-3 border-primary" novalidate>
          <div class="form-error"></div>
          <h6>Twoja propozycja dla drugiej strony</h6>
          <label class="form-label small mb-1">Kwota dla kierowcy (puste = cena algorytmu)</label>
          <div class="input-group mb-2"><input name="amount" data-type="number" class="form-control" inputmode="decimal"
            placeholder="${esc(feasible[0].amount)}"><span class="input-group-text">zł</span></div>
          <label class="form-label small mb-1 d-flex justify-content-between">
            <span>Ile płaci nadawca</span><span data-share-label></span></label>
          <input name="sender_share_pct" data-type="number" type="range" class="form-range" min="0" max="100" step="5"
            value="${isSender ? 100 : 0}">
          <input name="note" class="form-control form-control-sm mt-2" maxlength="300"
            placeholder="Wiadomość do ${isSender ? "odbiorcy" : "nadawcy"} (opcjonalnie)">
          <button class="btn btn-primary w-100 mt-3">Wyślij propozycję</button>
          <div class="small text-muted mt-2">Po wysłaniu ${isSender ? "odbiorca" : "nadawca"} może zaakceptować,
            złożyć kontrofertę albo odrzucić. Gdy się zgodzicie – decyduje kierowca.</div>
        </form>` : ""}
      </div>
      <div class="col-lg-7"><div id="map" class="tx-map tx-map-tall"></div>${legend()}
        <div class="small text-muted">Fioletowa linia: pozostała trasa wybranego kierowcy; pomarańczowa – Twoja paczka.</div></div>
    </div>`;

  const map = createMap($("#map", root));
  let routeLayer = null;
  const pkgLayer = drawPackages(map, [pkg], { color: COLORS.express, fit: false });
  const selected = () => quotes[Number(root.querySelector('input[name="quote"]:checked')?.value)];
  const showRoute = () => {
    if (routeLayer) routeLayer.remove();
    routeLayer = null;
    const q = selected();
    if (q?.route) routeLayer = drawRoute(map, q.route);
    else map.fitBounds(L.latLngBounds([[pkg.pickup.lat, pkg.pickup.lng], [pkg.delivery.lat, pkg.delivery.lng]]).pad(0.3));
    pkgLayer.eachLayer((l) => l.bringToFront?.());
  };
  root.querySelectorAll('input[name="quote"]').forEach((r) => r.addEventListener("change", () => {
    $('input[name="amount"]', root).placeholder = selected().amount;
    showRoute();
  }));
  showRoute();

  const form = $("form", root);
  if (form) {
    const share = form.sender_share_pct;
    const label = $("[data-share-label]", root);
    const updateShare = () => { label.textContent = `nadawca ${share.value}% · odbiorca ${100 - share.value}%`; };
    share.addEventListener("input", updateShare);
    updateShare();

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = readForm(form);
      data.driver = selected().driver.id;
      if (data.amount === null) delete data.amount;
      try {
        const neg = await withBusy($("button", form), () => api.post(`/packages/${pkg.id}/negotiations/`, data));
        toast("Rozpoczęto negocjację – druga strona musi zaakceptować warunki.");
        navigate(`#/negotiations/${neg.id}`);
      } catch (err) {
        showErrors(form, err);
      }
    });
  }
  return () => map.remove();
}
