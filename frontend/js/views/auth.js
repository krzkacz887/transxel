import { session } from "../session.js";
import { $, readForm, showErrors, toast, withBusy } from "../ui.js";

const DEMO = ["nadawca1", "odbiorca1", "kierowca1"];

export async function loginView(root, { query }) {
  root.innerHTML = `
    <div class="row justify-content-center"><div class="col-md-6 col-lg-4">
      <div class="card p-4 shadow-sm">
        <h4 class="mb-3">Logowanie</h4>
        <form novalidate>
          <div class="form-error"></div>
          <div class="mb-3"><label class="form-label">Login</label>
            <input name="username" class="form-control" autocomplete="username" required autofocus></div>
          <div class="mb-3"><label class="form-label">Hasło</label>
            <input name="password" type="password" class="form-control" autocomplete="current-password" required></div>
          <button class="btn btn-primary w-100">Zaloguj</button>
        </form>
    </div></div>`;
  const form = $("form", root);
  root.querySelectorAll(".demo").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    form.username.value = a.dataset.u;
    form.password.value = "demo1234";
  }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { username, password } = readForm(form);
    try {
      await withBusy($("button", form), () => session.login(username, password));
      toast(`Witaj, ${session.user.name}!`);
      location.hash = query.get("next") ? `#${query.get("next")}` : session.homePath();
    } catch (err) {
      showErrors(form, err);
    }
  });
}

const ROLES = [
  ["sender", "Nadawca", "wysyłam paczki"],
  ["recipient", "Odbiorca", "zamawiam paczki od nadawców"],
  ["driver", "Kierowca", "odbieram i dowożę po drodze"],
];

export async function registerView(root) {
  root.innerHTML = `
    <div class="row justify-content-center"><div class="col-md-8 col-lg-6">
      <div class="card p-4 shadow-sm">
        <h4 class="mb-3">Załóż konto</h4>
        <form novalidate>
          <div class="form-error"></div>
          <div class="mb-3"><div class="form-label">Typ konta</div>
            ${ROLES.map(([v, label, hint], i) => `
              <div class="form-check"><input class="form-check-input" type="radio" name="role" id="role-${v}" value="${v}" ${i === 0 ? "checked" : ""}>
                <label class="form-check-label" for="role-${v}"><b>${label}</b> <span class="text-muted">– ${hint}</span></label></div>`).join("")}
          </div>
          <div class="row g-3">
            <div class="col-sm-6"><label class="form-label">Login *</label>
              <input name="username" class="form-control" autocomplete="username" required></div>
            <div class="col-sm-6"><label class="form-label">E-mail</label>
              <input name="email" type="email" class="form-control"></div>
            <div class="col-sm-6"><label class="form-label">Imię</label><input name="first_name" class="form-control"></div>
            <div class="col-sm-6"><label class="form-label">Nazwisko</label><input name="last_name" class="form-control"></div>
            <div class="col-sm-6"><label class="form-label">Telefon</label><input name="phone" class="form-control"></div>
            <div class="col-sm-6"></div>
            <div class="col-sm-6"><label class="form-label">Hasło *</label>
              <input name="password1" type="password" class="form-control" autocomplete="new-password"></div>
            <div class="col-sm-6"><label class="form-label">Powtórz hasło *</label>
              <input name="password2" type="password" class="form-control" autocomplete="new-password"></div>
          </div>
          <button class="btn btn-primary w-100 mt-4">Utwórz konto</button>
        </form>
      </div>
    </div></div>`;
  const form = $("form", root);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await withBusy($("button.btn-primary", form), () => session.register(readForm(form)));
      toast("Konto utworzone. Ustaw swój domyślny adres.");
      location.hash = "#/account";
    } catch (err) {
      showErrors(form, err);
    }
  });
}
