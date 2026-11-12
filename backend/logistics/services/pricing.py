"""
Wycena dorzucenia paczki do trwającej trasy kierowcy (ekspres, „spoza planu”).

Cena wynika z tego, ile kierowcę kosztuje objazd:
    cena = (opłata bazowa + km objazdu × stawka + min objazdu × stawka + kg × stawka) × mnożnik ekspresu
z dolnym progiem MIN_PRICE i zaokrągleniem do pełnych złotych.

Kolejność dotychczasowych przystanków się nie zmienia – nowa paczka jest wstawiana
w najtańsze możliwe miejsce (z zachowaniem ładowności i czasu zmiany).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.conf import settings

from ..models import Driver, Package, Route
from . import geo
from .optimizer import DELIVERY, PICKUP, Job, evaluate_insertion
from .planning import PlanningError, current_position

NEW_KEY = "__new__"


@dataclass
class Quote:
    driver: Driver
    route: Optional[Route]
    feasible: bool
    reason: str = ""
    amount: Decimal = Decimal("0")
    detour_km: float = 0.0
    detour_min: float = 0.0
    breakdown: list[dict] = field(default_factory=list)
    source: str = ""

    def as_json(self) -> dict:
        return {
            "feasible": self.feasible, "reason": self.reason, "amount": str(self.amount),
            "detour_km": round(self.detour_km, 2), "detour_min": round(self.detour_min, 1),
            "breakdown": self.breakdown, "source": self.source,
            "route_id": self.route.pk if self.route else None,
        }


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_from_detour(detour_km: float, detour_min: float, weight_kg: float) -> tuple[Decimal, list[dict]]:
    p = settings.PRICING
    items = [
        {"label": "Opłata bazowa", "value": _money(p["BASE_FEE"])},
        {"label": f"Objazd {detour_km:.1f} km × {p['PER_KM']} zł", "value": _money(detour_km * p["PER_KM"])},
        {"label": f"Czas {detour_min:.0f} min × {p['PER_MIN']} zł", "value": _money(detour_min * p["PER_MIN"])},
        {"label": f"Waga {weight_kg:.1f} kg × {p['PER_KG']} zł", "value": _money(weight_kg * p["PER_KG"])},
    ]
    subtotal = sum(i["value"] for i in items)
    total = subtotal * Decimal(str(p["EXPRESS_MULTIPLIER"]))
    items.append({"label": f"Mnożnik ekspresu × {p['EXPRESS_MULTIPLIER']}", "value": _money(total - subtotal)})
    total = max(total, Decimal(str(p["MIN_PRICE"])))
    total = total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    for i in items:
        i["value"] = str(i["value"])
    return _money(total), items


def quote_for_driver(package: Package, driver: Driver) -> Quote:
    route = driver.active_route
    if route is None:
        return Quote(driver, None, False, "Kierowca nie ma teraz aktywnej trasy.")
    try:
        start = current_position(driver)
    except PlanningError as exc:
        return Quote(driver, route, False, str(exc))

    remaining = list(route.stops.filter(completed_at__isnull=True).select_related("package").order_by("order"))
    if any(s.package_id == package.pk for s in remaining):
        return Quote(driver, route, False, "Ta paczka już jest w trasie tego kierowcy.")

    # węzły: 0 = pozycja kierowcy, potem pozostałe przystanki, na końcu nowa paczka
    points = [start]
    nodes: dict[tuple, int] = {}
    for s in remaining:
        points.append((s.lat, s.lng))
        nodes[(s.package_id, s.kind)] = len(points) - 1
    points += [package.pickup_point, package.delivery_point]
    new_p, new_d = len(points) - 2, len(points) - 1

    jobs, sequence = [], []
    for s in remaining:
        if s.kind == DELIVERY:
            jobs.append(Job(key=s.package_id, pickup=nodes.get((s.package_id, PICKUP)),
                            delivery=nodes[(s.package_id, DELIVERY)],
                            weight=float(s.package.weight_kg), mandatory=True))
        sequence.append((s.package_id, s.kind))
    new_job = Job(key=NEW_KEY, pickup=new_p, delivery=new_d, weight=float(package.weight_kg))

    durations, distances, source = geo.travel_matrix(points)
    remaining_s = route.remaining_shift_s
    res = evaluate_insertion(
        durations, jobs, sequence, new_job, start=0,
        capacity=float(driver.vehicle_capacity_kg),
        max_duration=remaining_s if remaining_s else None,
        service_time=settings.ROUTING["SERVICE_TIME_S"], distance=distances,
    )
    if not res.feasible:
        return Quote(driver, route, False, res.reason, source=source)

    km, minutes = max(res.delta_distance, 0) / 1000, max(res.delta_duration_s, 0) / 60
    amount, items = price_from_detour(km, minutes, float(package.weight_kg))
    return Quote(driver, route, True, amount=amount, detour_km=km, detour_min=minutes,
                 breakdown=items, source=source)


def quotes_for_package(package: Package, limit: Optional[int] = None) -> list[Quote]:
    """Wyceny od kierowców w trasie – najbliżsi najpierw, wykonalne posortowane po cenie."""
    limit = limit or settings.PRICING["QUOTE_MAX_DRIVERS"]
    drivers = list(Driver.objects.filter(routes__status=Route.Status.ACTIVE).distinct())

    def dist(d):
        try:
            return geo.haversine_m(current_position(d), package.pickup_point)
        except PlanningError:
            return float("inf")

    drivers.sort(key=dist)
    quotes = [quote_for_driver(package, d) for d in drivers[:limit]]
    return sorted(quotes, key=lambda q: (not q.feasible, q.amount))
