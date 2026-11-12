"""Planowanie trasy kierowcy i obsługa przystanków (logika biznesowa)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Driver, Package, Route, RouteStop
from . import geo
from .optimizer import PICKUP, Job, plan_route

log = logging.getLogger("logistics")


class PlanningError(Exception):
    pass


@dataclass
class PlanningResult:
    route: Optional[Route]
    new_packages: int = 0
    matrix_source: str = "osrm"
    messages: list[str] = field(default_factory=list)


def current_position(driver: Driver, explicit: Optional[tuple] = None) -> tuple[float, float]:
    """Punkt, z którego liczymy dalszą trasę kierowcy.

    Kolejność: wskazany jawnie (kliknięty na mapie) → ostatni wykonany przystanek aktywnej trasy
    → start aktywnej trasy → baza kierowcy z profilu.
    """
    if explicit and explicit[0] is not None and explicit[1] is not None:
        return float(explicit[0]), float(explicit[1])
    route = driver.active_route
    if route:
        last_done = route.stops.filter(completed_at__isnull=False).order_by("-completed_at").first()
        if last_done:
            return last_done.lat, last_done.lng
        return route.start_lat, route.start_lng
    if driver.point:
        return driver.point
    raise PlanningError("Brak punktu startu – ustaw bazę w profilu albo wskaż start na mapie.")


def plan_for_driver(
    driver: Driver,
    start: Optional[tuple] = None,
    capacity_kg: Optional[float] = None,
    shift_hours: Optional[float] = None,
    max_new: Optional[int] = None,
    take_new: bool = True,
) -> PlanningResult:
    """Układa (lub przeplanowuje) trasę kierowcy.

    Paczki w aucie i już przypisane są obowiązkowe; wolne paczki z puli dobierane
    są tylko, jeśli opłaca się je wziąć po drodze.
    """
    cfg = settings.ROUTING
    start_pt = current_position(driver, start)
    capacity = float(capacity_kg if capacity_kg is not None else driver.vehicle_capacity_kg)
    if shift_hours is None:
        old = driver.active_route
        remaining = old.remaining_shift_s if old else None
        shift_hours = remaining / 3600 if remaining else cfg["DEFAULT_SHIFT_HOURS"]
    shift_s = max(float(shift_hours), 0.25) * 3600

    mine = list(Package.objects.filter(
        driver=driver, status__in=[Package.Status.ASSIGNED, Package.Status.PICKED_UP]))
    pool: list[Package] = []
    if take_new:
        free = Package.objects.filter(status=Package.Status.NEW, driver__isnull=True).order_by("created_at")[:1000]
        free = [p for p in free if float(p.weight_kg) <= capacity]
        free.sort(key=lambda p: geo.haversine_m(start_pt, p.pickup_point))
        pool = free[: cfg["MAX_CANDIDATES"]]

    if not mine and not pool:
        return PlanningResult(route=None, messages=["Brak paczek do obsłużenia."])

    points = [start_pt]
    jobs: list[Job] = []
    mine_ids = {p.pk for p in mine}
    for pkg in mine + pool:
        p_idx = None
        if pkg.status != Package.Status.PICKED_UP:
            points.append(pkg.pickup_point)
            p_idx = len(points) - 1
        points.append(pkg.delivery_point)
        jobs.append(Job(key=pkg.pk, pickup=p_idx, delivery=len(points) - 1,
                        weight=float(pkg.weight_kg), mandatory=pkg.pk in mine_ids))

    durations, distances, source = geo.travel_matrix(points)
    plan = plan_route(durations, jobs, start=0, end=None, capacity=capacity, max_duration=shift_s,
                      service_time=cfg["SERVICE_TIME_S"], max_jobs=max_new)
    if not plan.stops:
        return PlanningResult(route=None, matrix_source=source, messages=[
            "Żadna paczka z puli nie mieści się w czasie zmiany lub ładowności pojazdu."])

    by_id = {p.pk: p for p in mine + pool}
    chosen_pool = [k for k in plan.served if k not in mine_ids]

    with transaction.atomic():
        locked = set(Package.objects.select_for_update()
                     .filter(pk__in=chosen_pool, status=Package.Status.NEW, driver__isnull=True)
                     .values_list("pk", flat=True))
        lost = set(chosen_pool) - locked
        stops = [s for s in plan.stops if s.job_key not in lost]

        Route.objects.filter(driver=driver, status=Route.Status.ACTIVE).update(status=Route.Status.REPLACED)
        route = Route.objects.create(driver=driver, start_lat=start_pt[0], start_lng=start_pt[1],
                                     shift_end=timezone.now() + timedelta(seconds=shift_s),
                                     total_duration_s=plan.total_duration_s, matrix_source=source)
        prev, dist_total = 0, 0.0
        for order, s in enumerate(stops, start=1):
            pkg = by_id[s.job_key]
            is_pickup = s.kind == PICKUP
            dist_total += distances[prev][s.node]
            prev = s.node
            RouteStop.objects.create(
                route=route, order=order, package=pkg,
                kind=RouteStop.Kind.PICKUP if is_pickup else RouteStop.Kind.DELIVERY,
                lat=points[s.node][0], lng=points[s.node][1],
                address=pkg.pickup_address if is_pickup else pkg.delivery_address, eta_s=s.arrival_s)
        route.total_distance_m = dist_total
        route.save(update_fields=["total_distance_m"])
        Package.objects.filter(pk__in=locked).update(status=Package.Status.ASSIGNED, driver=driver)

    geometry = geo.route_geometry([start_pt] + [points[s.node] for s in stops])
    route.geometry = {"type": "LineString", "coordinates": geometry["coordinates"]}
    if geometry["source"] == "osrm" and not lost:
        route.total_distance_m = geometry["distance_m"]
    route.save(update_fields=["geometry", "total_distance_m"])


    result = PlanningResult(route=route, new_packages=len(locked), matrix_source=source)
    if source != "osrm":
        result.messages.append("Serwer tras był niedostępny – czasy są szacunkowe (linia prosta).")
    if lost:
        result.messages.append(f"{len(lost)} paczek zostało w międzyczasie przejętych przez innego kierowcę.")
    return result


def complete_stop(stop: RouteStop, user) -> str:
    """Oznacza przystanek jako wykonany. Zwraca komunikat dla użytkownika."""
    if stop.route.driver_id != user.pk:
        raise PlanningError("To nie jest Twój przystanek.")
    if stop.completed_at:
        raise PlanningError("Przystanek był już oznaczony.")
    pkg = stop.package
    now = timezone.now()
    with transaction.atomic():
        if stop.kind == RouteStop.Kind.PICKUP:
            if pkg.status != Package.Status.ASSIGNED:
                raise PlanningError(f"Paczki {pkg.tracking_code} nie można odebrać (status: {pkg.get_status_display()}).")
            pkg.status, pkg.picked_up_at = Package.Status.PICKED_UP, now
            msg = f"Odebrano paczkę {pkg.tracking_code}."
        else:
            if pkg.status != Package.Status.PICKED_UP:
                raise PlanningError(f"Najpierw odbierz paczkę {pkg.tracking_code}.")
            pkg.status, pkg.delivered_at = Package.Status.DELIVERED, now
            msg = f"Doręczono paczkę {pkg.tracking_code}."
        pkg.save(update_fields=["status", "picked_up_at", "delivered_at"])
        stop.completed_at = now
        stop.save(update_fields=["completed_at"])
        if stop.route.finish_if_done():
            msg += " Trasa zakończona!"
    return msg
