"""Kierowca: wyznaczanie trasy z punktów paczek, pula wolnych paczek, odbiór / doręczenie."""
from ..forms import PlanRouteForm
from ..models import Package, RouteStop
from ..services.planning import complete_stop, plan_for_driver
from .base import DRIVER, ApiView, get_or_404, validate
from .serializers import pool_package_json, route_json


def _summary(driver) -> dict:
    route = driver.active_route
    onboard = Package.objects.filter(driver=driver, status=Package.Status.PICKED_UP)
    return {
        "route": route_json(route, detailed=True),
        "onboard_count": onboard.count(),
        "onboard_weight_kg": round(sum(float(p.weight_kg) for p in onboard), 2),
        "capacity_kg": float(driver.vehicle_capacity_kg),
        "base": {"address": driver.address, "lat": driver.lat, "lng": driver.lng} if driver.point else None,
        "remaining_shift_h": round(route.remaining_shift_s / 3600, 1) if route and route.shift_end else None,
    }


class DriverRouteView(ApiView):
    roles = (DRIVER,)

    def get(self, request):
        return _summary(request.account)

    def post(self, request):
        cd = validate(PlanRouteForm(request.data))
        start = (cd.get("start_lat"), cd.get("start_lng"))
        result = plan_for_driver(
            request.account, start=start if None not in start else None,
            capacity_kg=cd.get("capacity_kg"), shift_hours=cd.get("shift_hours"),
            max_new=cd.get("max_new"), take_new=cd.get("take_new", False))
        return {**_summary(request.account), "new_packages": result.new_packages,
                "matrix_source": result.matrix_source, "messages": result.messages}, 201


class DriverPoolView(ApiView):
    roles = (DRIVER,)

    def get(self, request):
        pool = Package.objects.filter(status=Package.Status.NEW, driver__isnull=True).order_by("created_at")[:300]
        return [pool_package_json(p) for p in pool]


class StopCompleteView(ApiView):
    roles = (DRIVER,)

    def post(self, request, pk):
        stop = get_or_404(RouteStop.objects.select_related("route", "package"), "Nie ma takiego przystanku.", pk=pk)
        message = complete_stop(stop, request.account)
        return {"message": message, **_summary(request.account)}
