import { api } from "../api.js";
import { createMap, drawPackages } from "../map.js";
import { session } from "../session.js";
import { $, esc, fmtDate, spinner, statusBadge } from "../ui.js";

const trackForm = (code = "") => `
  <form class="d-flex gap-2" data-track>
    <input name="code" class="form-control" placeholder="Numer przesyłki, np. TX1A2B3C4D" value="${esc(code)}" required>
    <button class="btn btn-primary">Szukaj</button>
  </form>`;

function bindTrack(root) {
  const form = $("[data-track]", root);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const code = form.code.value.trim().toUpperCase();
    if (code) location.hash = `#/track/${encodeURIComponent(code)}`;
  });
}

export async function homeView(root) {
  if (session.user) {
    location.hash = session.homePath();
    return;
  }
  root.innerHTML = `
    <div class="card p-4 mb-4">
      <h1 class="h3">Kurier bez magazynu</h1>
      <p>transXel nie wozi paczek do sortowni. Kierowca jedzie trasą wyznaczoną z punktów odbioru
        i doręczenia – odbiera paczkę u nadawcy i po drodze dowozi ją odbiorcy.</p>
      <ul class="mb-3">
        <li><b>Trasa z punktów</b> – algorytm układa kolejność odbiorów i doręczeń (odbiór przed doręczeniem, ładowność, czas zmiany).</li>
        <li><b>Ekspres w trakcie trasy</b> – paczkę spoza planu można dorzucić do trwającej trasy; cena wynika z objazdu.</li>
        <li><b>Negocjacja trzech stron</b> – nadawca i odbiorca dzielą się kosztem, kierowca akceptuje albo proponuje swoją cenę.</li>
      </ul>
      <div class="d-flex gap-2"><a href="#/register" class="btn btn-primary">Załóż konto</a>
        <a href="#/login" class="btn btn-outline-secondary">Zaloguj</a></div>
    </div>
    <div class="card p-4"><h2 class="h5">Śledź przesyłkę</h2>${trackForm()}</div>`;
  bindTrack(root);
}

export async function trackView(root, { code }) {
  root.innerHTML = spinner();
  let pkg;
  try {
    pkg = await api.get(`/track/${encodeURIComponent(code)}/`);
  } catch (e) {
    root.innerHTML = `<div class="card p-3 mb-4">${trackForm(code)}</div>
      <div class="alert alert-warning">${esc(e.message)}</div>`;
    bindTrack(root);
    return;
  }
  const steps = [
    ["Nadana", pkg.created_at, true],
    ["Odebrana przez kuriera", pkg.picked_up_at, Boolean(pkg.picked_up_at)],
    ["Doręczona", pkg.delivered_at, Boolean(pkg.delivered_at)],
  ];
  root.innerHTML = `
    <div class="card p-3 mb-4">${trackForm(pkg.code)}</div>
    <div class="row g-4">
      <div class="col-lg-5">
        <div class="card p-4">
          <div class="d-flex justify-content-between align-items-center mb-3">
            <h4 class="mb-0">${esc(pkg.code)}</h4>${statusBadge(pkg.status, pkg.status_label)}</div>
          <div class="mb-2">${esc(pkg.pickup.address)}</div>
          <div class="mb-3">${esc(pkg.delivery.address)}</div>
          <ul class="timeline">${steps.map(([label, at, ok]) =>
            `<li class="${ok ? "ok" : ""}"><b>${label}</b> <span class="text-muted small">${ok ? fmtDate(at) : ""}</span></li>`).join("")}</ul>
          ${pkg.driver_name ? `<div class="small text-muted mt-3">Kurier: ${esc(pkg.driver_name)}</div>` : ""}
        </div>
      </div>
      <div class="col-lg-7"><div id="map" class="tx-map"></div></div>
    </div>`;
  bindTrack(root);
  const map = createMap($("#map", root));
  drawPackages(map, [pkg], { color: "#6f42c1" });
  return () => map.remove();
}
