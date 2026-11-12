/** Punkt wejścia: trasy widoków, pasek nawigacji, odświeżanie licznika negocjacji. */
import { setUnauthorizedHandler } from "./api.js";
import { POLL_MS } from "./config.js";
import { route, start } from "./router.js";
import { session } from "./session.js";
import { esc, toast } from "./ui.js";

import { accountView } from "./views/account.js";
import { loginView, registerView } from "./views/auth.js";
import { driverView } from "./views/driver.js";
import { expressView } from "./views/express.js";
import { homeView, trackView } from "./views/home.js";
import { negotiationDetailView, negotiationListView } from "./views/negotiations.js";
import { packageDetailView, packageFormView, packageListView } from "./views/packages.js";

route("/", homeView, "public");
route("/track/:code", trackView, "public");
route("/login", loginView, "guest");
route("/register", registerView, "guest");
route("/account", accountView);
route("/packages", packageListView, "party");
route("/packages/new", packageFormView, "party");
route("/packages/:id", packageDetailView, "party");
route("/packages/:id/edit", packageFormView, "party");
route("/packages/:id/express", expressView, "party");
route("/negotiations", negotiationListView);
route("/negotiations/:id", negotiationDetailView);
route("/driver", driverView, "driver");

function renderNav(user) {
  const links = document.getElementById("nav-links");
  const right = document.getElementById("nav-user");
  const badge = user?.pending_negotiations
    ? ` <span class="badge rounded-pill text-bg-danger" title="Czeka na Twoją decyzję">${user.pending_negotiations}</span>` : "";
  const item = (href, text, extra = "") =>
    `<li class="nav-item"><a class="nav-link" href="${href}">${text}${extra}</a></li>`;

  if (!user) {
    links.innerHTML = item("#/", "Śledzenie");
    right.innerHTML = item("#/login", "Zaloguj") + item("#/register", "Rejestracja");
    return;
  }
  links.innerHTML = user.role === "driver"
    ? item("#/driver", "Moja trasa") + item("#/negotiations", "Ekspresy", badge)
    : item("#/packages", "Paczki") +
      item("#/packages/new", user.role === "sender" ? "Nadaj paczkę" : "Zamów paczkę") +
      item("#/negotiations", "Negocjacje", badge);
  right.innerHTML = `
    <li class="nav-item dropdown">
      <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">
        ${esc(user.name)} <span class="badge text-bg-light border">${esc(user.role_label)}</span>
      </a>
      <ul class="dropdown-menu dropdown-menu-end">
        <li><a class="dropdown-item" href="#/account">Konto i adres</a></li>
        <li><hr class="dropdown-divider"></li>
        <li><a class="dropdown-item" href="#/logout" data-logout>Wyloguj</a></li>
      </ul>
    </li>`;
  right.querySelector("[data-logout]").addEventListener("click", async (e) => {
    e.preventDefault();
    await session.logout();
    toast("Wylogowano.", "info");
    location.hash = "#/";
  });
}

session.onChange(renderNav);
setUnauthorizedHandler(() => {
  session.set(null);
  toast("Sesja wygasła – zaloguj się ponownie.", "warning");
  location.hash = "#/login";
});

// licznik „czeka na Twoją decyzję” – odświeżany w tle
setInterval(() => {
  if (session.user && document.visibilityState === "visible") session.load().catch(() => {});
}, POLL_MS);

(async () => {
  try {
    await session.load();
  } catch (e) {
    toast(e.message, "danger");
  }
  renderNav(session.user);
  start();
})();
