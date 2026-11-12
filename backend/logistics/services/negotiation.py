"""
Pipeline negocjacji ceny za dorzucenie paczki do trwającej trasy.

    ┌────────────┐   ┌──────────────────────────┐   ┌──────────────┐   ┌───────────────────┐
    │ 1. WYCENA  │──▶│ 2. PARTIES               │──▶│ 3. DRIVER    │──▶│ ACCEPTED          │
    │ algorytmu  │   │ nadawca <-> odbiorca     │   │ akceptuj     │   │ paczka w trasie   │
    └────────────┘   │ kontroferty              │   │ zmień cenę  ─┐   └───────────────────┘
                     └──────────────────────────┘   │ odrzuć       │            ▲
                                                    └──────────────│   ┌───────────────────┐
                                                                   └──▶│ 4. CONFIRM        │
                                                                       │ obie strony       │
                                                                       │ potwierdzają cenę │
                                                                       └───────────────────┘
    Z każdego otwartego etapu: odrzucenie/wycofanie → REJECTED / CANCELLED (paczka wraca do puli).

Reguły zapisane są deklaratywnie w tabeli TRANSITIONS: dla każdej akcji – na jakim etapie
i kto może ją wykonać (+ dodatkowy warunek). Dzięki temu UI pokazuje tylko dozwolone
przyciski, a serwer i tak sprawdza wszystko ponownie.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import Driver, Negotiation, NegotiationEvent, Package, User
from . import pricing
from .planning import PlanningError, plan_for_driver

Stage = Negotiation.Stage
Act = NegotiationEvent.Action
SENDER, RECIPIENT, DRIVER = User.Role.SENDER, User.Role.RECIPIENT, User.Role.DRIVER
PARTIES = (SENDER, RECIPIENT)


class NegotiationError(Exception):
    pass


# ----------------------------------------------------------------- pomocnicze
def role_in(neg: Negotiation, user) -> Optional[str]:
    """Rola użytkownika w TEJ negocjacji (nie tylko typ konta)."""
    if user.pk == neg.package.sender_id:
        return SENDER
    if user.pk == neg.package.recipient_id:
        return RECIPIENT
    if user.pk == neg.driver_id:
        return DRIVER
    return None


def _ok_field(role):
    return "sender_ok" if role == SENDER else "recipient_ok"


def _other(role):
    return RECIPIENT if role == SENDER else SENDER


def _parse_amount(amount) -> Decimal:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise NegotiationError("Podaj poprawną kwotę.")
    if value <= 0 or value > Decimal("100000"):
        raise NegotiationError("Kwota musi być większa od zera.")
    return value


def _parse_share(share, default) -> int:
    if share in (None, ""):
        return default
    try:
        share = int(share)
    except (TypeError, ValueError):
        raise NegotiationError("Udział nadawcy musi być liczbą 0–100.")
    if not 0 <= share <= 100:
        raise NegotiationError("Udział nadawcy musi być liczbą 0–100.")
    return share


# ------------------------------------------------------------ definicja kroków
@dataclass(frozen=True)
class Transition:
    action: str
    stages: tuple
    roles: tuple
    label: str
    style: str = "primary"
    with_amount: bool = False        # formularz z kwotą
    with_share: bool = False         # formularz z podziałem kosztu
    guard: Optional[Callable[[Negotiation, str], bool]] = None

    def allowed(self, neg: Negotiation, role: Optional[str]) -> bool:
        return (neg.stage in self.stages and role in self.roles
                and (self.guard is None or self.guard(neg, role)))


def _is_responder(neg, role):          # strona, która ma odpowiedzieć na ostatnią ofertę
    return role in PARTIES and neg.last_offer_role != role


def _is_waiting(neg, role):            # strona, która złożyła ostatnią ofertę i czeka
    return role in PARTIES and neg.last_offer_role == role


def _can_counter(neg, role):
    return _is_responder(neg, role) and neg.party_rounds < settings.PRICING["MAX_PARTY_ROUNDS"]


def _not_confirmed(neg, role):
    return role in PARTIES and not getattr(neg, _ok_field(role))


TRANSITIONS: list[Transition] = [
    # etap 2: nadawca ⇄ odbiorca
    Transition("accept", (Stage.PARTIES,), PARTIES, "Akceptuję warunki", "success", guard=_is_responder),
    Transition("counter", (Stage.PARTIES,), PARTIES, "Kontroferta", "outline-primary",
               with_amount=True, with_share=True, guard=_can_counter),
    Transition("reject", (Stage.PARTIES,), PARTIES, "Odrzuć", "outline-danger", guard=_is_responder),
    Transition("cancel", (Stage.PARTIES,), PARTIES, "Wycofaj ofertę", "outline-secondary", guard=_is_waiting),
    # etap 3: kierowca
    Transition("accept", (Stage.DRIVER,), (DRIVER,), "Akceptuję – dodaj do trasy", "success"),
    Transition("counter", (Stage.DRIVER,), (DRIVER,), "Zmień cenę", "outline-primary", with_amount=True,
               guard=lambda n, r: n.driver_counters < settings.PRICING["DRIVER_MAX_COUNTERS"]),
    Transition("reject", (Stage.DRIVER,), (DRIVER,), "Odrzuć", "outline-danger"),
    Transition("cancel", (Stage.DRIVER,), PARTIES, "Wycofaj zlecenie", "outline-secondary"),
    # etap 4: potwierdzenie ceny kierowcy
    Transition("confirm", (Stage.CONFIRM,), PARTIES, "Potwierdzam cenę kierowcy", "success", guard=_not_confirmed),
    Transition("reject", (Stage.CONFIRM,), PARTIES + (DRIVER,), "Odrzuć", "outline-danger"),
]


def available_actions(neg: Negotiation, user) -> list[Transition]:
    role = role_in(neg, user)
    return [t for t in TRANSITIONS if t.allowed(neg, role)]


def needs_action(neg: Negotiation, user) -> bool:
    """Czy negocjacja czeka na decyzję tego użytkownika (wycofanie się nie liczy)."""
    return any(t.action != "cancel" for t in available_actions(neg, user))


def negotiations_for(user):
    return (Negotiation.objects.filter(Q(package__sender=user.pk) | Q(package__recipient=user.pk)
                                       | Q(driver=user.pk))
            .select_related("package", "driver", "package__sender", "package__recipient"))


def pending_for(user) -> list[Negotiation]:
    return [n for n in negotiations_for(user).filter(stage__in=Negotiation.OPEN_STAGES) if needs_action(n, user)]


def _log(neg, actor, role, action, note="", amount=None, share=None):
    NegotiationEvent.objects.create(
        negotiation=neg, actor=actor, role=role or "", action=action, note=note[:300],
        amount=amount, sender_share_pct=share, stage_after=neg.stage)



# ------------------------------------------------------------------- start
def start(package: Package, driver: Driver, initiator, sender_share_pct=50, amount=None, note="") -> Negotiation:
    """Etap 1: algorytm wycenia objazd, inicjator otwiera negocjację (od razu akceptuje swoje warunki)."""
    if not package.is_party(initiator):
        raise NegotiationError("Negocjację może rozpocząć tylko nadawca lub odbiorca paczki.")
    if package.status != Package.Status.NEW:
        raise NegotiationError("Ekspres można zamówić tylko dla paczki oczekującej na kuriera.")
    quote = pricing.quote_for_driver(package, driver)   # zawsze liczymy na nowo – nie ufamy przeglądarce
    if not quote.feasible:
        raise NegotiationError(f"Ten kierowca nie może wziąć paczki: {quote.reason}")

    role = SENDER if initiator.pk == package.sender_id else RECIPIENT
    share = _parse_share(sender_share_pct, 50)
    offer = _parse_amount(amount) if amount not in (None, "") else quote.amount

    with transaction.atomic():
        pkg = Package.objects.select_for_update().get(pk=package.pk)
        if pkg.status != Package.Status.NEW:
            raise NegotiationError("Paczka zmieniła status – odśwież stronę.")
        neg = Negotiation.objects.create(
            package=pkg, driver=driver, route=quote.route, initiated_by=initiator, stage=Stage.PARTIES,
            quoted_amount=quote.amount, quote=quote.as_json(), amount=offer, sender_share_pct=share,
            last_offer_role=role, **{_ok_field(role): True})
        _log(neg, None, "system", Act.QUOTE, amount=quote.amount,
             note=f"Objazd {quote.detour_km:.1f} km / {quote.detour_min:.0f} min")
        _log(neg, initiator, role, Act.OPEN, note=note, amount=offer, share=share)
        pkg.status = Package.Status.NEGOTIATING
        pkg.save(update_fields=["status"])
    return neg


# ------------------------------------------------------------------- akcje
def perform(neg: Negotiation, user, action: str, amount=None, sender_share_pct=None, note="") -> str:
    """Wykonuje krok pipeline'u. Zwraca komunikat dla użytkownika."""
    replan = False
    with transaction.atomic():
        neg = Negotiation.objects.select_for_update().select_related("package").get(pk=neg.pk)
        role = role_in(neg, user)
        if not any(t.action == action for t in available_actions(neg, user)):
            raise NegotiationError("Ta akcja nie jest teraz dostępna (ktoś mógł już odpowiedzieć – odśwież).")
        pkg = neg.package

        if neg.stage == Stage.PARTIES:
            if action == "accept":
                setattr(neg, _ok_field(role), True)
                neg.stage = Stage.DRIVER          # oferujący już się zgodził, więc obie strony zgodne
                msg = "Warunki uzgodnione – zlecenie trafiło do kierowcy."
                _log(neg, user, role, Act.ACCEPT, note, neg.amount, neg.sender_share_pct)
            elif action == "counter":
                neg.amount = _parse_amount(amount)
                neg.sender_share_pct = _parse_share(sender_share_pct, neg.sender_share_pct)
                neg.last_offer_role = role
                setattr(neg, _ok_field(role), True)
                setattr(neg, _ok_field(_other(role)), False)
                neg.party_rounds += 1
                msg = "Wysłano kontrofertę."
                _log(neg, user, role, Act.COUNTER, note, neg.amount, neg.sender_share_pct)
            elif action == "reject":
                msg = _close(neg, user, role, Stage.REJECTED, Act.REJECT, note)
            else:  # cancel
                msg = _close(neg, user, role, Stage.CANCELLED, Act.CANCEL, note)

        elif neg.stage == Stage.DRIVER:
            if action == "accept":
                msg = _accept(neg, pkg, user, role, note)
                replan = True
            elif action == "counter":
                neg.amount = _parse_amount(amount)
                neg.last_offer_role = DRIVER
                neg.sender_ok = neg.recipient_ok = False
                neg.driver_counters += 1
                neg.stage = Stage.CONFIRM
                msg = "Wysłano nową cenę – czekamy na potwierdzenie nadawcy i odbiorcy."
                _log(neg, user, role, Act.COUNTER, note, neg.amount, neg.sender_share_pct)
            elif action == "reject":
                msg = _close(neg, user, role, Stage.REJECTED, Act.REJECT, note)
            else:  # cancel przez stronę
                msg = _close(neg, user, role, Stage.CANCELLED, Act.CANCEL, note)

        else:  # CONFIRM
            if action == "confirm":
                setattr(neg, _ok_field(role), True)
                _log(neg, user, role, Act.CONFIRM, note, neg.amount, neg.sender_share_pct)
                if neg.sender_ok and neg.recipient_ok:
                    msg = _accept(neg, pkg, None, "system", "Obie strony potwierdziły cenę kierowcy.")
                    replan = True
                else:
                    msg = "Potwierdzono – czekamy na drugą stronę."
            else:  # reject
                msg = _close(neg, user, role, Stage.REJECTED, Act.REJECT, note)

        neg.save()

    if replan:
        msg += " " + _add_to_route(neg)
    return msg


def _close(neg, user, role, stage, action, note) -> str:
    neg.stage = stage
    neg.closed_at = timezone.now()
    _log(neg, user, role, action, note, neg.amount, neg.sender_share_pct)
    Package.objects.filter(pk=neg.package_id, status=Package.Status.NEGOTIATING).update(status=Package.Status.NEW)
    return "Negocjacja zakończona bez dodania do trasy – paczka wróciła do zwykłej puli."


def _accept(neg, pkg, user, role, note) -> str:
    neg.stage = Stage.ACCEPTED
    neg.closed_at = timezone.now()
    _log(neg, user, role, Act.ACCEPT, note, neg.amount, neg.sender_share_pct)
    pkg.status = Package.Status.ASSIGNED
    pkg.driver_id = neg.driver_id
    pkg.price = neg.amount
    pkg.sender_pays = neg.sender_amount
    pkg.recipient_pays = neg.recipient_amount
    pkg.save(update_fields=["status", "driver", "price", "sender_pays", "recipient_pays"])
    return f"Zaakceptowano: {neg.amount} zł."


def _add_to_route(neg) -> str:
    """Ostatni etap: przeplanowanie trasy kierowcy z nową (obowiązkową) paczką."""
    try:
        result = plan_for_driver(neg.driver, take_new=False)
    except PlanningError as exc:
        _log(neg, None, "system", Act.ADDED, note=f"Nie udało się przeplanować: {exc}")
        return "Paczka przypisana kierowcy – trasa zostanie przeliczona przy najbliższym planowaniu."
    note = f"Trasa #{result.route.pk}, {result.route.stops.count()} przystanków" if result.route else ""
    _log(neg, None, "system", Act.ADDED, note=note)
    return "Paczka dodana do trasy kierowcy."
