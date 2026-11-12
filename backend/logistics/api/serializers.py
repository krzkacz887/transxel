"""
Zamiana modeli na JSON. Kwoty pieniężne jako tekst ("40.00"), żeby nie tracić precyzji.
"""
from __future__ import annotations

from django.conf import settings

from ..models import Driver, Negotiation, Package, Route, RouteStop, User
from ..services import negotiation as pipeline

STEPS = [
    ("quote", "Wycena algorytmu"),
    ("parties", "Nadawca ⇄ odbiorca"),
    ("driver", "Decyzja kierowcy"),
    ("confirm", "Potwierdzenie ceny"),
    ("accepted", "W trasie"),
]


def money(x):
    return None if x is None else str(x)


def dt(x):
    return x.isoformat() if x else None


# ------------------------------------------------------------------ konta
def user_brief(u):
    if u is None:
        return None
    return {"id": u.pk, "username": u.username, "name": u.display_name, "phone": u.phone}


def contact_json(u):
    return {**user_brief(u), "address": u.address, "lat": u.lat, "lng": u.lng}


def account_json(acc) -> dict:
    data = {
        "id": acc.pk, "username": acc.username, "role": acc.role, "role_label": User.Role(acc.role).label,
        "name": acc.display_name, "first_name": acc.first_name, "last_name": acc.last_name,
        "email": acc.email, "phone": acc.phone, "address": acc.address, "lat": acc.lat, "lng": acc.lng,
    }
    if isinstance(acc, Driver):
        data.update(vehicle_name=acc.vehicle_name, vehicle_capacity_kg=float(acc.vehicle_capacity_kg))
    if acc.role == User.Role.SENDER:
        data["company"] = acc.company
    return data


# ------------------------------------------------------------------ paczki
def _point(address, lat, lng, contact=None):
    data = {"address": address, "lat": lat, "lng": lng}
    if contact is not None:
        data["contact"] = contact
    return data


def package_json(p: Package, me=None) -> dict:
    mine = me is not None and p.is_party(me)
    return {
        "id": p.pk, "code": p.tracking_code, "status": p.status, "status_label": p.get_status_display(),
        "description": p.description, "weight_kg": float(p.weight_kg), "notes": p.notes,
        "sender": user_brief(p.sender), "recipient": user_brief(p.recipient), "driver": user_brief(p.driver),
        "pickup": _point(p.pickup_address, p.pickup_lat, p.pickup_lng, p.pickup_contact),
        "delivery": _point(p.delivery_address, p.delivery_lat, p.delivery_lng, p.delivery_contact),
        "price": money(p.price), "sender_pays": money(p.sender_pays), "recipient_pays": money(p.recipient_pays),
        "created_at": dt(p.created_at), "picked_up_at": dt(p.picked_up_at), "delivered_at": dt(p.delivered_at),
        "my_side": ("sender" if me.pk == p.sender_id else "recipient") if mine else None,
        "can_edit": mine and p.created_by_id == me.pk and p.status == Package.Status.NEW,
        "can_express": mine and p.status == Package.Status.NEW,
    }


def tracking_json(p: Package) -> dict:
    """Publiczne śledzenie – bez kontaktów, uwag i cen."""
    return {
        "code": p.tracking_code, "status": p.status, "status_label": p.get_status_display(),
        "pickup": _point(p.pickup_address, p.pickup_lat, p.pickup_lng),
        "delivery": _point(p.delivery_address, p.delivery_lat, p.delivery_lng),
        "created_at": dt(p.created_at), "picked_up_at": dt(p.picked_up_at), "delivered_at": dt(p.delivered_at),
        "driver_name": p.driver.first_name if p.driver else None,
    }


def pool_package_json(p: Package) -> dict:
    """Wolna paczka widziana przez kierowcę (pula do dobrania)."""
    return {"id": p.pk, "code": p.tracking_code, "description": p.description, "weight_kg": float(p.weight_kg),
            "pickup": _point(p.pickup_address, p.pickup_lat, p.pickup_lng),
            "delivery": _point(p.delivery_address, p.delivery_lat, p.delivery_lng)}


# ------------------------------------------------------------------ trasy
def stop_json(s: RouteStop, detailed: bool) -> dict:
    data = {"id": s.pk, "order": s.order, "kind": s.kind, "kind_label": s.get_kind_display(),
            "lat": s.lat, "lng": s.lng, "address": s.address, "eta": dt(s.eta),
            "done": s.completed_at is not None, "completed_at": dt(s.completed_at),
            "package": {"id": s.package_id, "code": s.package.tracking_code}}
    if detailed:   # tylko dla kierowcy tej trasy
        p = s.package
        data["package"].update(
            description=p.description, weight_kg=float(p.weight_kg), status=p.status,
            status_label=p.get_status_display(), price=money(p.price), notes=p.notes,
            contact=p.pickup_contact if s.kind == RouteStop.Kind.PICKUP else p.delivery_contact,
            person=user_brief(p.sender if s.kind == RouteStop.Kind.PICKUP else p.recipient))
    return data


def route_json(route: Route | None, only_remaining=False, detailed=False) -> dict | None:
    if route is None:
        return None
    stops = route.stops.select_related("package", "package__sender", "package__recipient", "route")
    if only_remaining:
        stops = stops.filter(completed_at__isnull=True)
    stops = list(stops)
    return {
        "id": route.pk, "status": route.status, "status_label": route.get_status_display(),
        "start": {"lat": route.start_lat, "lng": route.start_lng},
        "distance_km": round(route.total_distance_m / 1000, 2),
        "duration_min": round(route.total_duration_s / 60),
        "created_at": dt(route.created_at), "shift_end": dt(route.shift_end),
        "matrix_source": route.matrix_source,
        "geometry": route.geometry or None,
        "stops": [stop_json(s, detailed) for s in stops],
        "done_count": sum(1 for s in stops if s.completed_at),
    }


# ------------------------------------------------------------------ wyceny i negocjacje
def quote_json(q) -> dict:
    return {
        **q.as_json(),
        "driver": {**user_brief(q.driver), "vehicle_name": q.driver.vehicle_name,
                   "vehicle_capacity_kg": float(q.driver.vehicle_capacity_kg)},
        "route": route_json(q.route, only_remaining=True) if q.route else None,
    }


def _event_json(e) -> dict:
    return {"id": e.pk, "created_at": dt(e.created_at), "role": e.role, "role_label": e.role_label,
            "actor": e.actor.username if e.actor else None, "action": e.action,
            "action_label": e.get_action_display(), "amount": money(e.amount),
            "sender_share_pct": e.sender_share_pct, "note": e.note}


def negotiation_json(neg: Negotiation, me, detailed=False) -> dict:
    pkg = neg.package
    actions = pipeline.available_actions(neg, me) if neg.is_open else []
    data = {
        "id": neg.pk, "stage": neg.stage, "stage_label": neg.get_stage_display(), "is_open": neg.is_open,
        "package": {"id": pkg.pk, "code": pkg.tracking_code, "description": pkg.description,
                    "weight_kg": float(pkg.weight_kg),
                    "pickup": _point(pkg.pickup_address, pkg.pickup_lat, pkg.pickup_lng),
                    "delivery": _point(pkg.delivery_address, pkg.delivery_lat, pkg.delivery_lng)},
        "sender": user_brief(pkg.sender), "recipient": user_brief(pkg.recipient),
        "driver": {**user_brief(neg.driver), "vehicle_name": neg.driver.vehicle_name},
        "quoted_amount": money(neg.quoted_amount), "amount": money(neg.amount),
        "sender_share_pct": neg.sender_share_pct, "recipient_share_pct": neg.recipient_share_pct,
        "sender_amount": money(neg.sender_amount), "recipient_amount": money(neg.recipient_amount),
        "sender_ok": neg.sender_ok, "recipient_ok": neg.recipient_ok,
        "last_offer_role": neg.last_offer_role, "party_rounds": neg.party_rounds,
        "max_party_rounds": settings.PRICING["MAX_PARTY_ROUNDS"],
        "updated_at": dt(neg.updated_at),
        "my_role": pipeline.role_in(neg, me),
        "my_turn": any(t.action != "cancel" for t in actions),
        "actions": [{"action": t.action, "label": t.label, "style": t.style,
                     "with_amount": t.with_amount, "with_share": t.with_share} for t in actions],
    }
    if detailed:
        events = list(neg.events.select_related("actor"))
        reached = {"quote", neg.stage, *(e.stage_after for e in events)}
        route = neg.driver.active_route
        data.update(
            quote=neg.quote,
            events=[_event_json(e) for e in events],
            steps=[{"key": k, "label": label, "reached": k in reached, "current": k == neg.stage}
                   for k, label in STEPS],
            driver_route=route_json(route, only_remaining=True) if route and neg.is_open else None,
        )
    return data
