/** Mapy: Leaflet + kafelki OSM. Geokodowanie idzie przez nasze API (/api/geocode/). */
import { api } from "./api.js";
import { DEFAULT_CENTER, MAP_TILES } from "./config.js";
import { esc } from "./ui.js";

export const COLORS = { P: "#0d6efd", D: "#198754", start: "#212529", done: "#adb5bd", express: "#fd7e14" };

export function createMap(el, center = DEFAULT_CENTER, zoom = 12) {
  const map = L.map(el).setView(center, zoom);
  L.tileLayer(MAP_TILES.url, {
    maxZoom: MAP_TILES.maxZoom,
    attribution: MAP_TILES.attribution,
    referrerPolicy: "strict-origin-when-cross-origin", // serwery OSM wymagają nagłówka Referer
  }).addTo(map);
  // mapa w ukrytym / właśnie wyrenderowanym kontenerze – przelicz rozmiar
  setTimeout(() => map.invalidateSize(), 50);
  return map;
}

export function pinIcon(kind, label = "", { done = false, color } = {}) {
  const bg = done ? COLORS.done : color || COLORS[kind] || COLORS.start;
  const shape = kind === "D" ? "tx-pin tx-pin-square" : "tx-pin";
  return L.divIcon({
    className: "",
    html: `<div class="${shape}" style="background:${bg}">${esc(label)}</div>`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

const ll = (p) => [p.lat, p.lng];

export function fitTo(map, points) {
  if (!points.length) return;
  if (points.length === 1) map.setView(points[0], 14);
  else map.fitBounds(L.latLngBounds(points).pad(0.15));
}

/** Trasa kierowcy: linia po drogach (OSRM) + ponumerowane przystanki. */
export function drawRoute(map, route, { fit = true, onStopClick, layer } = {}) {
  layer = layer || L.layerGroup().addTo(map);
  const points = [];
  const coords = route.geometry?.coordinates;
  if (coords && coords.length > 1) {
    const line = coords.map((c) => [c[1], c[0]]);
    L.polyline(line, { color: "#6f42c1", weight: 5, opacity: 0.75 }).addTo(layer);
    points.push(...line);
  }
  L.marker(ll(route.start), { icon: pinIcon("start", "S") }).bindPopup("Start trasy").addTo(layer);
  points.push(ll(route.start));
  route.stops.forEach((s) => {
    const m = L.marker(ll(s), { icon: pinIcon(s.kind, s.order, { done: s.done }) })
      .bindPopup(`<b>${s.order}. ${esc(s.kind_label)}</b> ${esc(s.package.code)}<br>${esc(s.address)}` +
        (s.done ? "<br><i>wykonano</i>" : ""))
      .addTo(layer);
    if (onStopClick) m.on("click", () => onStopClick(s));
    points.push(ll(s));
  });
  if (fit) fitTo(map, points);
  return layer;
}

/** Paczki jako pary punktów odbiór → doręczenie połączone przerywaną linią. */
export function drawPackages(map, packages, { fit = true, color = "#6c757d", layer } = {}) {
  layer = layer || L.layerGroup().addTo(map);
  const points = [];
  packages.forEach((p) => {
    const a = ll(p.pickup), b = ll(p.delivery);
    L.polyline([a, b], { color, weight: 2, dashArray: "5 6", opacity: 0.8 }).addTo(layer);
    const info = `<b>${esc(p.code)}</b>${p.description ? " – " + esc(p.description) : ""}`;
    L.marker(a, { icon: pinIcon("P", "O") }).bindPopup(`${info}<br>Odbiór: ${esc(p.pickup.address)}`).addTo(layer);
    L.marker(b, { icon: pinIcon("D", "D") }).bindPopup(`${info}<br>Doręczenie: ${esc(p.delivery.address)}`).addTo(layer);
    points.push(a, b);
  });
  if (fit) fitTo(map, points);
  return layer;
}

export const legend = () => `
  <div class="tx-legend text-muted mt-2">
    <span><i style="background:${COLORS.start}"></i> start</span>
    <span><i style="background:${COLORS.P}"></i> odbiór</span>
    <span><i class="sq" style="background:${COLORS.D}"></i> doręczenie</span>
    <span><i style="background:${COLORS.done}"></i> wykonane</span>
  </div>`;

export async function reverseGeocode(lat, lng) {
  try {
    return (await api.get("/reverse-geocode/", { lat, lng })).name;
  } catch {
    return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  }
}

/**
 * Pole adresu z podpowiedziami + punkt na mapie (przeciągalny pinezka).
 * HTML pola: <div class="position-relative"><div class="input-group">
 *   <input name="..._address"> <button data-search>…</button></div><div data-results></div></div>
 */
export function pointPicker({ map, wrapper, kind, label, value, onChange }) {
  const input = wrapper.querySelector("input");
  const results = wrapper.querySelector("[data-results]");
  const searchBtn = wrapper.querySelector("[data-search]");
  let point = value?.lat != null ? { lat: value.lat, lng: value.lng } : null;
  let marker = null;

  const placeMarker = (fly) => {
    if (!point) {
      if (marker) { marker.remove(); marker = null; }
      return;
    }
    if (marker) marker.setLatLng(ll(point));
    else {
      marker = L.marker(ll(point), { icon: pinIcon(kind, label), draggable: true }).addTo(map);
      marker.on("dragend", async () => {
        const p = marker.getLatLng();
        point = { lat: p.lat, lng: p.lng };
        input.value = await reverseGeocode(p.lat, p.lng);
        onChange?.();
      });
    }
    if (fly) map.setView(ll(point), 15);
  };

  const setPoint = (lat, lng, fly = true) => {
    point = { lat, lng };
    placeMarker(fly);
    onChange?.();
  };

  // ręczna zmiana adresu unieważnia punkt – serwer zgeokoduje adres przy zapisie
  input.addEventListener("input", () => { point = null; placeMarker(false); });

  const search = async () => {
    const q = input.value.trim();
    if (q.length < 3) return;
    results.innerHTML = '<div class="list-group"><div class="list-group-item small text-muted">Szukam…</div></div>';
    try {
      const found = await api.get("/geocode/", { q });
      if (!found.length) {
        results.innerHTML = '<div class="list-group"><div class="list-group-item small text-danger">Nie znaleziono – kliknij punkt na mapie.</div></div>';
        return;
      }
      results.innerHTML = `<div class="list-group results-list">${found.map((r, i) =>
        `<button type="button" class="list-group-item list-group-item-action small" data-i="${i}">${esc(r.name)}</button>`).join("")}</div>`;
      results.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
        const r = found[Number(b.dataset.i)];
        input.value = r.name;
        results.innerHTML = "";
        setPoint(r.lat, r.lng);
      }));
    } catch (e) {
      results.innerHTML = `<div class="list-group"><div class="list-group-item small text-danger">${esc(e.message)}</div></div>`;
    }
  };
  searchBtn.addEventListener("click", search);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); search(); }
    if (e.key === "Escape") results.innerHTML = "";
  });

  placeMarker(false);
  return {
    get: () => ({ address: input.value.trim(), lat: point?.lat ?? null, lng: point?.lng ?? null }),
    async setFromMap(lat, lng) {
      setPoint(lat, lng, false);
      input.value = "Szukam adresu…";
      input.value = await reverseGeocode(lat, lng);
    },
    set(address, lat, lng) {
      input.value = address || "";
      if (lat != null) setPoint(lat, lng);
      else { point = null; placeMarker(false); }
    },
    point: () => point,
  };
}
