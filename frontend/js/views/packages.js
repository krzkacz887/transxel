/** Paczki nadawcy / odbiorcy: lista z filtrami i mapą, formularz (nadanie / zamówienie / edycja), szczegóły. */
import { api } from "../api.js";
import { createMap, drawPackages, fitTo, legend, pointPicker } from "../map.js";
import { session } from "../session.js";
import {
  $, STATUS_OPTIONS, emptyState, esc, fmtDate, money, navigate, readForm, showErrors, spinner, stageBadge,
  statusBadge, toast, withBusy,
} from "../ui.js";

const ACTIVE = ["new", "negotiating", "assigned", "picked_up"];

// ------------------------------------------------------------------ lista
export async function packageListView(root, { query }) {
  const direction = query.get("direction") || "";
  const status = query.get("status") || "";
  root.innerHTML = spinner();
  const packages = await api.get("/packages/", { direction, status });
  const me = session.user;
  const tab = (value, label) =>
    `<a class="nav-link ${direction === value ? "active" : ""}" href="#/packages?direction=${value}&status=${status}">${label}</a>`;

  root.innerHTML = `
    ${me.pending_negotiations ? `<div class="alert alert-primary d-flex justify-content-between align-items-center">
      <span>${me.pending_negotiations} negocjacj${me.pending_negotiations === 1 ? "a czeka" : "e czekają"} na Twoją decyzję.</span>
      <a class="btn btn-primary btn-sm" href="#/negotiations">Przejdź</a></div>` : ""}
    <div class="row g-4">
      <div class="col-xl-7">
        <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
          <h3 class="mb-0">Moje paczki</h3>
          <a href="#/packages/new" class="btn btn-primary">            ${me.role === "sender" ? "Nadaj paczkę" : "Zamów paczkę"}</a>
        </div>
        <div class="card">
          <div class="card-header bg-white d-flex flex-wrap gap-2 justify-content-between align-items-center">
            <nav class="nav nav-pills nav-sm">${tab("", "Wszystkie")}${tab("sent", "Wysyłane")}${tab("received", "Odbierane")}</nav>
            <select class="form-select form-select-sm w-auto" data-status>
              <option value="">Każdy status</option>
              ${STATUS_OPTIONS.map(([v, l]) => `<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`).join("")}
            </select>
          </div>
          ${packages.length ? `<div class="table-responsive"><table class="table align-middle mb-0">
            <thead class="small text-muted"><tr><th>Numer</th><th>Trasa</th><th>Strona</th><th>Status</th><th class="text-end">Cena</th></tr></thead>
            <tbody>${packages.map((p) => `
              <tr class="package-row" data-id="${p.id}">
                <td><b>${esc(p.code)}</b><div class="small text-muted">${esc(p.description || "paczka")}, ${p.weight_kg} kg</div></td>
                <td class="small"><div>${esc(p.pickup.address)}</div>
                  <div>${esc(p.delivery.address)}</div></td>
                <td class="small">${p.my_side === "sender"
                  ? `<span class="text-muted">do</span> ${esc(p.recipient.name)}`
                  : `<span class="text-muted">od</span> ${esc(p.sender.name)}`}</td>
                <td>${statusBadge(p.status, p.status_label)}</td>
                <td class="text-end small">${p.price ? money(p.price) : "—"}</td>
              </tr>`).join("")}</tbody></table></div>`
            : emptyState("Brak paczek dla wybranych filtrów.")}
        </div>
      </div>
      <div class="col-xl-5">
        <div id="map" class="tx-map tx-map-tall"></div>
        <div class="small text-muted mt-1">Na mapie: paczki w trakcie realizacji.</div>
      </div>
    </div>`;

  $("[data-status]", root).addEventListener("change", (e) =>
    navigate(`#/packages?direction=${direction}&status=${e.target.value}`));
  root.querySelectorAll(".package-row").forEach((tr) =>
    tr.addEventListener("click", () => navigate(`#/packages/${tr.dataset.id}`)));

  const map = createMap($("#map", root));
  drawPackages(map, packages.filter((p) => ACTIVE.includes(p.status)));
  return () => map.remove();
}

// ------------------------------------------------------------------ formularz
const addressField = (prefix, label) => `
  <div class="mb-2">
    <label class="form-label mb-1">${label}</label>
    <div class="position-relative" data-picker="${prefix}">
      <div class="input-group">
        <input name="${prefix}_address" class="form-control" placeholder="Wpisz adres i naciśnij Enter albo kliknij na mapie">
        <button type="button" class="btn btn-outline-secondary" data-search></button>
      </div>
      <div data-results></div>
    </div>
  </div>
  <input name="${prefix}_contact" class="form-control form-control-sm mb-3" placeholder="Kontakt na miejscu (imię, telefon) – opcjonalnie">`;

export async function packageFormView(root, { id }) {
  root.innerHTML = spinner();
  const me = session.user;
  const editing = Boolean(id);
  const [contacts, pkg] = await Promise.all([api.get("/contacts/"), editing ? api.get(`/packages/${id}/`) : null]);
  if (editing && !pkg.can_edit) {
    toast("Tej paczki nie można już edytować.", "warning");
    navigate(`#/packages/${id}`);
    return;
  }
  const isSender = me.role === "sender";
  const counterpart = isSender ? "recipient" : "sender";
  const currentCounterpart = pkg?.[counterpart]?.id;

  root.innerHTML = `
    <div class="row g-4">
      <div class="col-lg-5">
        <h3>${editing ? `Edycja ${esc(pkg.code)}` : isSender ? "Nadaj paczkę" : "Zamów paczkę od nadawcy"}</h3>
        <p class="text-muted small">${isSender
          ? "Wybierz odbiorcę – jego domyślny adres wstawi się sam. Kurier odbierze paczkę spod Twojego adresu."
          : "Wybierz nadawcę, od którego zamawiasz – kurier odbierze paczkę u niego i przywiezie pod Twój adres."}</p>
        <form class="card p-3" novalidate>
          <div class="form-error"></div>
          <label class="form-label mb-1">${isSender ? "Odbiorca" : "Nadawca"}</label>
          <select name="${counterpart}" class="form-select mb-3" ${editing ? "disabled" : ""}>
            <option value="">— wybierz —</option>
            ${contacts.map((c) => `<option value="${c.id}" ${c.id === currentCounterpart ? "selected" : ""}>
              ${esc(c.name)} (${esc(c.username)})${c.address ? " – " + esc(c.address) : ""}</option>`).join("")}
          </select>
          <div class="row g-2 mb-3">
            <div class="col-8"><input name="description" class="form-control" placeholder="Zawartość, np. Książki" maxlength="200"></div>
            <div class="col-4"><div class="input-group"><input name="weight_kg" data-type="number" class="form-control" value="1" inputmode="decimal">
              <span class="input-group-text">kg</span></div></div>
          </div>
          ${addressField("pickup", "Adres odbioru")}
          ${addressField("delivery", "Adres doręczenia")}
          <textarea name="notes" class="form-control mb-3" rows="2" placeholder="Uwagi dla kuriera (opcjonalnie)"></textarea>
          <div class="d-flex gap-2">
            <button class="btn btn-primary flex-fill">${editing ? "Zapisz zmiany" : isSender ? "Nadaj paczkę" : "Zamów paczkę"}</button>
            <a class="btn btn-outline-secondary" href="${editing ? `#/packages/${id}` : "#/packages"}">Anuluj</a>
          </div>
        </form>
      </div>
      <div class="col-lg-7">
        <div class="d-flex justify-content-between align-items-center mb-2 map-mode">
          <span class="small text-muted">Kliknięcie na mapie ustawia:</span>
          <div class="btn-group" role="group">
            <input type="radio" class="btn-check" name="mode" id="mode-p" value="pickup" checked>
            <label class="btn btn-outline-primary" for="mode-p">punkt odbioru</label>
            <input type="radio" class="btn-check" name="mode" id="mode-d" value="delivery">
            <label class="btn btn-outline-success" for="mode-d">punkt doręczenia</label>
          </div>
        </div>
        <div id="map" class="tx-map tx-map-tall"></div>
      </div>
    </div>`;

  const form = $("form", root);
  const map = createMap($("#map", root));
  const fit = () => fitTo(map, [pickup.point(), delivery.point()].filter(Boolean).map((p) => [p.lat, p.lng]));
  const pickup = pointPicker({ map, wrapper: $('[data-picker="pickup"]', root), kind: "P", label: "O", onChange: fit });
  const delivery = pointPicker({ map, wrapper: $('[data-picker="delivery"]', root), kind: "D", label: "D", onChange: fit });

  if (editing) {
    ["description", "notes"].forEach((f) => { form[f].value = pkg[f]; });
    form.weight_kg.value = pkg.weight_kg;
    form.pickup_contact.value = pkg.pickup.contact;
    form.delivery_contact.value = pkg.delivery.contact;
    pickup.set(pkg.pickup.address, pkg.pickup.lat, pkg.pickup.lng);
    delivery.set(pkg.delivery.address, pkg.delivery.lat, pkg.delivery.lng);
  } else if (me.address) {
    (isSender ? pickup : delivery).set(me.address, me.lat, me.lng);   // mój domyślny adres
  }
  fit();

  // wybór kontrahenta podstawia jego domyślny adres
  form[counterpart].addEventListener("change", (e) => {
    const c = contacts.find((x) => String(x.id) === e.target.value);
    if (!c?.address) return;
    (isSender ? delivery : pickup).set(c.address, c.lat, c.lng);
    form[isSender ? "delivery_contact" : "pickup_contact"].value = [c.name, c.phone].filter(Boolean).join(", ");
    fit();
  });

  map.on("click", (e) => {
    const mode = root.querySelector('input[name="mode"]:checked').value;
    (mode === "pickup" ? pickup : delivery).setFromMap(e.latlng.lat, e.latlng.lng);
    if (mode === "pickup") root.querySelector("#mode-d").checked = true;   // wygodnie: następne kliknięcie = doręczenie
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = readForm(form);
    delete data.mode;
    const p = pickup.get(), d = delivery.get();
    Object.assign(data, {
      pickup_address: p.address, pickup_lat: p.lat, pickup_lng: p.lng,
      delivery_address: d.address, delivery_lat: d.lat, delivery_lng: d.lng,
    });
    if (editing) delete data[counterpart];
    else data[counterpart] = data[counterpart] ? Number(data[counterpart]) : null;
    try {
      const saved = await withBusy($("button.btn-primary", form), () =>
        editing ? api.patch(`/packages/${id}/`, data) : api.post("/packages/", data));
      toast(editing ? "Zapisano zmiany." : `${isSender ? "Nadano" : "Zamówiono"} paczkę ${saved.code}. Kurier weźmie ją po drodze.`);
      navigate(`#/packages/${saved.id}`);
    } catch (err) {
      showErrors(form, err);
    }
  });
  return () => map.remove();
}

// ------------------------------------------------------------------ szczegóły
export async function packageDetailView(root, { id }) {
  root.innerHTML = spinner();
  const pkg = await api.get(`/packages/${id}/`);
  const steps = [
    ["Utworzona", pkg.created_at, true],
    ["Odebrana przez kuriera", pkg.picked_up_at, Boolean(pkg.picked_up_at)],
    ["Doręczona", pkg.delivered_at, Boolean(pkg.delivered_at)],
  ];
  const person = (label, u) => `<div class="col-6"><div class="small text-muted">${label}</div>
    ${u ? `<b>${esc(u.name)}</b><div class="small">${esc(u.phone || "")}</div>` : "—"}</div>`;

  root.innerHTML = `
    <div class="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-3">
      <h3 class="mb-0">${esc(pkg.code)} ${statusBadge(pkg.status, pkg.status_label)}</h3>
      <div class="d-flex gap-2">
        ${pkg.can_express ? `<a class="btn btn-primary" href="#/packages/${pkg.id}/express">Zamów ekspres</a>` : ""}
        ${pkg.can_edit ? `<a class="btn btn-outline-secondary" href="#/packages/${pkg.id}/edit">Edytuj</a>
          <button class="btn btn-outline-danger" data-delete>Usuń</button>` : ""}
      </div>
    </div>
    <div class="row g-4">
      <div class="col-lg-5">
        <div class="card p-3 mb-3">
          <div class="mb-2"><b>Odbiór:</b> ${esc(pkg.pickup.address)}
            ${pkg.pickup.contact ? `<div class="small text-muted ms-4">${esc(pkg.pickup.contact)}</div>` : ""}</div>
          <div class="mb-2"><b>Doręczenie:</b> ${esc(pkg.delivery.address)}
            ${pkg.delivery.contact ? `<div class="small text-muted ms-4">${esc(pkg.delivery.contact)}</div>` : ""}</div>
          <div class="small text-muted">${esc(pkg.description || "paczka")}, ${pkg.weight_kg} kg
            ${pkg.notes ? `· <i>${esc(pkg.notes)}</i>` : ""}</div>
          <hr>
          <div class="row g-2">${person("Nadawca", pkg.sender)}${person("Odbiorca", pkg.recipient)}${person("Kierowca", pkg.driver)}
            <div class="col-6"><div class="small text-muted">Cena ekspresu</div><b>${money(pkg.price)}</b>
              ${pkg.price ? `<div class="small">nadawca ${money(pkg.sender_pays)} · odbiorca ${money(pkg.recipient_pays)}</div>` : ""}</div>
          </div>
        </div>
        <div class="card p-3 mb-3"><h6>Przebieg</h6><ul class="timeline">${steps.map(([l, at, ok]) =>
          `<li class="${ok ? "ok" : ""}"><b>${l}</b> <span class="small text-muted">${ok ? fmtDate(at) : ""}</span></li>`).join("")}</ul>
          <div class="small mt-2">Publiczny link: <a href="#/track/${esc(pkg.code)}">#/track/${esc(pkg.code)}</a></div>
        </div>
        ${pkg.negotiations?.length ? `<div class="card p-3"><h6>Negocjacje ekspresu</h6>
          <div class="list-group list-group-flush">${pkg.negotiations.map((n) => `
            <a class="list-group-item list-group-item-action d-flex justify-content-between" href="#/negotiations/${n.id}">
              <span>#${n.id} · ${esc(n.driver.name)} · ${money(n.amount)}</span>${stageBadge(n)}</a>`).join("")}</div></div>` : ""}
        ${pkg.status === "new" ? `<div class="alert alert-light small mt-3">          Paczka czeka w puli – kierowca weźmie ją, gdy wyznaczy trasę w okolicy. Spieszysz się? Zamów ekspres u kierowcy, który już jest w trasie.</div>` : ""}
      </div>
      <div class="col-lg-7"><div id="map" class="tx-map"></div>${legend()}</div>
    </div>`;

  $("[data-delete]", root)?.addEventListener("click", async (e) => {
    if (!confirm(`Usunąć paczkę ${pkg.code}?`)) return;
    try {
      await withBusy(e.currentTarget, () => api.del(`/packages/${pkg.id}/`));
      toast(`Usunięto paczkę ${pkg.code}.`, "info");
      navigate("#/packages");
    } catch (err) {
      toast(err.message, "danger");
    }
  });

  const map = createMap($("#map", root));
  drawPackages(map, [pkg], { color: "#6f42c1" });
  return () => map.remove();
}
