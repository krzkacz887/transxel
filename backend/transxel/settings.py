"""Ustawienia projektu transXel."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me-transxel")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "logistics",
]

MIDDLEWARE = [
    "logistics.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "transxel.urls"

WSGI_APPLICATION = "transxel.wsgi.application"

# --- CORS ----------------------------------------------------------------------
# Frontend (../frontend) działa pod innym adresem niż API, więc przeglądarka wysyła
# zapytania cross-origin. logistics.middleware.CorsMiddleware wpuszcza tylko te originy.
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
CORS_URL_PREFIX = "/api/"
CORS_ALLOW_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS = ["authorization", "content-type"]
CORS_PREFLIGHT_MAX_AGE = 86400

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LANGUAGE_CODE = "pl"
TIME_ZONE = "Europe/Warsaw"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Własny model użytkownika (z klasami dziedziczącymi: Sender, Recipient, Driver).
# UWAGA: ustawienie musi być przed pierwszą migracją – przy zmianie usuń db.sqlite3.
AUTH_USER_MODEL = "logistics.User"


# --- Usługi mapowe -----------------------------------------------------------
# OSRM: macierz czasów przejazdu (table) i geometria trasy (route).
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
# Nominatim: geokodowanie adresów (adres -> współrzędne i odwrotnie).
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
# Nominatim wymaga identyfikującego User-Agenta (polityka użycia OSM).
GEO_USER_AGENT = os.environ.get("GEO_USER_AGENT", "transXel/1.0 (projekt edukacyjny)")
GEO_COUNTRY_CODES = os.environ.get("GEO_COUNTRY_CODES", "pl")
GEO_TIMEOUT_S = 10

# --- Planowanie tras ---------------------------------------------------------
ROUTING = {
    "SERVICE_TIME_S": 180,        # czas postoju na odbiór/doręczenie
    "MAX_CANDIDATES": 40,         # ile najbliższych paczek z puli rozważać (OSRM demo: ~100 punktów)
    "DEFAULT_SHIFT_HOURS": 8,
    "FALLBACK_SPEED_KMH": 30,     # gdy OSRM niedostępny – szacunek po linii prostej
    "FALLBACK_DETOUR": 1.35,      # współczynnik krętości dróg
}

# --- Wycena ekspresu (dorzucenie paczki do trwającej trasy) -------------------
PRICING = {
    "BASE_FEE": 12,            # zł – opłata bazowa
    "PER_KM": 2.5,             # zł za każdy km objazdu
    "PER_MIN": 0.8,            # zł za każdą minutę objazdu (z postojami)
    "PER_KG": 0.3,             # zł za kg
    "EXPRESS_MULTIPLIER": 1.2, # dopłata za zmianę planu w trakcie trasy
    "MIN_PRICE": 20,           # zł – cena minimalna
    "MAX_PARTY_ROUNDS": 10,    # ile kontrofert mogą wymienić nadawca i odbiorca
    "DRIVER_MAX_COUNTERS": 1,  # ile razy kierowca może zmienić cenę
    "QUOTE_MAX_DRIVERS": 5,    # ilu najbliższych kierowców w trasie wyceniać
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"logistics": {"handlers": ["console"], "level": "INFO"}},
}
