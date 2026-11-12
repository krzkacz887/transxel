/** Zalogowany użytkownik (stan współdzielony przez widoki i pasek nawigacji). */
import { api, hasToken, setToken } from "./api.js";

const listeners = new Set();

export const session = {
  user: null,

  async load() {
    if (!hasToken()) {
      this.set(null);
      return null;
    }
    try {
      this.set(await api.get("/me/"));
    } catch (e) {
      if (e.status === 401) this.set(null);
      else throw e;
    }
    return this.user;
  },

  async login(username, password) {
    const res = await api.post("/auth/login/", { username, password });
    setToken(res.token);
    this.set(res.user);
  },

  async register(data) {
    const res = await api.post("/auth/register/", data);
    setToken(res.token);
    this.set(res.user);
  },

  async logout() {
    try { await api.post("/auth/logout/"); } catch { /* token i tak usuwamy */ }
    setToken(null);
    this.set(null);
  },

  set(user) {
    this.user = user;
    listeners.forEach((fn) => fn(user));
  },

  onChange(fn) {
    listeners.add(fn);
  },

  offChange(fn) {
    listeners.delete(fn);
  },

  get isDriver() { return this.user?.role === "driver"; },
  get isParty() { return this.user && this.user.role !== "driver"; },
  homePath() {
    if (!this.user) return "#/";
    return this.isDriver ? "#/driver" : "#/packages";
  },
};
