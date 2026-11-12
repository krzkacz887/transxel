"""Geokodowanie (Nominatim) przez backend – frontend nie łączy się bezpośrednio z usługami mapowymi."""
from ..services import geo
from .base import ApiError, ApiView


class GeocodeView(ApiView):

    def get(self, request):
        q = request.GET.get("q", "").strip()
        if len(q) < 3:
            raise ApiError("Wpisz co najmniej 3 znaki.", 400)
        try:
            results = geo.geocode(q, limit=5)
        except geo.GeoError as exc:
            raise ApiError(str(exc), 502)
        return [{"lat": r.lat, "lng": r.lng, "name": r.display_name} for r in results]


class ReverseGeocodeView(ApiView):

    def get(self, request):
        try:
            lat, lng = float(request.GET["lat"]), float(request.GET["lng"])
        except (KeyError, ValueError):
            raise ApiError("Podaj lat i lng.", 400)
        try:
            name = geo.reverse_geocode(lat, lng)
        except geo.GeoError as exc:
            raise ApiError(str(exc), 502)
        return {"name": name or f"{lat:.5f}, {lng:.5f}"}
