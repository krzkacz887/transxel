# transXel – dostawa paczek bez magazynu

Aplikacja dla kuriera, odbiorcy i nadawcy paczki, pozwalająca na podróż przesyłki bez znalezienia się w magazynie. Wyznacza optymalną trasę dla dostawcy między interesantami, daje możliwość dodania paczki w trakcie przejazdu po wynegocjowaniu odpowiedniej ceny.

```
transxel/
├── backend/    Django 5 – REST API (JSON), logika biznesowa, SQLite
└── frontend/   JavaScript + Bootstrap 5 + Leaflet
```

## Uruchomienie

Wymagany Python 3.10+. Potrzebne są dwa terminale.

**1. Backend – http://localhost:8000**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt                       # instalacja wymaganych bibliotek
python manage.py migrate                              # migracja bazy danych
python manage.py seed_demo                            # konta demo + 20 paczek w Warszawie, kierowca1 od razu w trasie
python manage.py runserver
```

**2. Frontend – http://localhost:5173**
```bash
cd frontend
python -m http.server 5173        # dowolny serwer plików statycznych (adres określony w settings.py backendu)
```
Konta demo mają hasło `demo1234`:
`nadawca1`, `nadawca2`, `odbiorca1`, `odbiorca2`, `kierowca1`, `kierowca2`.

## Funkcje

| Rola | Co może |
|---|---|
| **Nadawca** | nadać paczkę do wybranego odbiorcy (jego adres domyślny wstawia się sam), edytować ją i usunąć, póki czeka w puli, zamówić ekspres |
| **Odbiorca** | zamówić paczkę od nadawcy (kurier odbierze ją u nadawcy i przywiezie pod adres odbiorcy), negocjować ekspres |
| **Kierowca** | **wyznaczyć trasę z punktów paczek**: start z bazy albo z punktu klikniętego na mapie, ładowność, czas pracy, limit nowych paczek; potem „Odebrano” / „Doręczono” i decyzje o ekspresach |
| **Każdy** | publiczne śledzenie przesyłki po numerze (bez danych kontaktowych) |

## Backend

```
backend/logistics/
  models.py            User + Sender / Recipient / Driver (dziedziczenie wielotabelowe), Package,
                       Route, RouteStop, Negotiation, NegotiationEvent, ApiToken
  services/            logika biznesowa – nie wie nic o HTTP
    optimizer.py         algorytm trasy (czysty Python)
    planning.py          planowanie trasy kierowcy, odbiór / doręczenie
    pricing.py           wycena ekspresu
    negotiation.py       maszyna stanów negocjacji
    geo.py               Nominatim + OSRM (cache, timeouty, tryb awaryjny)
  api/                 warstwa HTTP
    base.py              ApiView: token, JSON in/out, kody błędów, role
    serializers.py       model → JSON
    accounts.py packages.py negotiations.py driver.py maps.py
    urls.py
  forms.py             walidacja danych wejściowych (formularze Django bez HTML)
  middleware.py        CORS
```

## Frontend

```
frontend/
  index.html          szkielet strony, Bootstrap / Leaflet z CDN
  css/app.css
  js/config.js        adres API, kafelki mapy
  js/api.js           klient REST: token, JSON, błędy (jedyne miejsce, które zna backend)
  js/session.js       zalogowany użytkownik
  js/router.js        router na hashu (#/packages/5) z ochroną tras wg roli
  js/map.js           mapa, trasa, pinezki, wybór punktu z podpowiedziami adresu
  js/ui.js            formatowanie, toasty, błędy walidacji przy polach
  js/views/           ekrany: home (śledzenie), auth, packages, express, negotiations, driver, account
```

## Mapy – darmowe usługi bez klucza
| Do czego                          | Usługa | Ustawienie w backendzie |
|-----------------------------------|---|---|
| podkład mapy                      | kafelki OpenStreetMap + Leaflet | `frontend/js/config.js` |
| adres - współrzędne               | Nominatim | `NOMINATIM_URL` |
| czasy przejazdu, trasa po drogach | OSRM (publiczny serwer demo) | `OSRM_URL` |

## Docker

Dodana jest też konfiguracja obrazu na dockera, można uruchomić w ten sposób:
```bash
docker compose up --build                               # buduje obrazy i startuje oba kontenery
docker compose exec backend python manage.py seed_demo  # uruchamia inicjalizacje bazy danych
```

## Użycie AI
W projekcie większość kodu powstała przy użyciu konsolowego Claude Code.
W całości napisał widok stron .js, logikę w wyliczaniu tras i negocjacji, mechanikę CORS do komunikacji między aplikacjami.
