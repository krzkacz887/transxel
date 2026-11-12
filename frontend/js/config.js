export const API_URL = "http://localhost:8000/api";

// Podkład mapy: oficjalne kafelki OpenStreetMap (bez klucza API).
export const MAP_TILES = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19,
};

export const DEFAULT_CENTER = [52.2297, 21.0122]; // Warszawa
export const POLL_MS = 20000;                     // odświeżanie licznika negocjacji i otwartej negocjacji
