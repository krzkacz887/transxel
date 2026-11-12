/** Konto: dane kontaktowe i domyślny adres (nadawca: odbiór, odbiorca: doręczenie, kierowca: baza). */
import { api } from "../api.js";
import { createMap, pointPicker } from "../map.js";
import { session } from "../session.js";
import { $, esc, readForm, showErrors, toast, withBusy } from "../ui.js";

const ADDRESS_LABEL = {
  sender: "Domyślny adres odbioru paczek",
  recipient: "Domyślny adres doręczenia",
  driver: "Baza – punkt startu trasy",
};

export async function accountView(root) {
  const me = session.user;
  const input = (name, label, attrs = "") =>
    `<div class="col-sm-6"><label class="form-label small mb-0">${label}</label>
      <input name="${name}" class="form-control" value="${esc(me[name] ?? "")}" ${attrs}></div>`;

  root.innerHTML = `
    <div class="row g-4">
      <div class="col-lg-5">
        <h3>Konto <span class="badge text-bg-light border fs-6">${esc(me.role_label)}</span></h3>
        <form class="card p-3" novalidate>
          <div class="form-error"></div>
          <div class="row g-2 mb-3">
            ${input("first_name", "Imię")}${input("last_name", "Nazwisko")}
            ${input("email", "E-mail", 'type="email"')}${input("phone", "Telefon")}
            ${me.role === "sender" ? input("company", "Firma") : ""}
            ${me.role === "driver" ? input("vehicle_name", "Pojazd") +
              input("vehicle_capacity_kg", "Ładowność [kg]", 'data-type="number" inputmode="decimal"') : ""}
          </div>
          <label class="form-label mb-1">${ADDRESS_LABEL[me.role]}</label>
          <div class="position-relative mb-3" data-picker>
            <div class="input-group">
              <input name="address" class="form-control" placeholder="Wpisz adres i naciśnij Enter albo kliknij na mapie">
              <button type="button" class="btn btn-outline-secondary" data-search></button>
            </div>
            <div data-results></div>
          </div>
          <button class="btn btn-primary">Zapisz</button>
        </form>
      </div>
      <div class="col-lg-7"><div id="map" class="tx-map tx-map-tall"></div></div>
    </div>`;

  const form = $("form", root);
  const map = createMap($("#map", root));
  const picker = pointPicker({ map, wrapper: $("[data-picker]", root), kind: me.role === "driver" ? "start" : me.role === "sender" ? "P" : "D",
    label: me.role === "driver" ? "B" : "★" });
  picker.set(me.address, me.lat, me.lng);
  map.on("click", (e) => picker.setFromMap(e.latlng.lat, e.latlng.lng));

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = readForm(form);
    const p = picker.get();
    Object.assign(data, { address: p.address, lat: p.lat, lng: p.lng });
    try {
      const user = await withBusy($("button.btn-primary", form), () => api.patch("/me/", data));
      session.set(user);
      picker.set(user.address, user.lat, user.lng);
      toast("Zapisano ustawienia.");
    } catch (err) {
      showErrors(form, err);
    }
  });
  return () => map.remove();
}
