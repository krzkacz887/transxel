import secrets
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


# =============================================================================
#  Użytkownicy: wspólna klasa User + trzy klasy dziedziczące (multi-table)
# =============================================================================
class User(AbstractUser):

    class Role(models.TextChoices):
        SENDER = "sender", "Nadawca"
        RECIPIENT = "recipient", "Odbiorca"
        DRIVER = "driver", "Kierowca"

    role = models.CharField("rola", max_length=10, choices=Role.choices, blank=True)
    phone = models.CharField("telefon", max_length=30, blank=True)

    @property
    def specific(self):
        if not self.role:
            return None
        if isinstance(self, ROLE_MODELS.get(self.role, ())):
            return self
        try:
            return getattr(self, self.role)
        except models.ObjectDoesNotExist:
            return None

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    is_sender = property(lambda self: self.role == self.Role.SENDER)
    is_recipient = property(lambda self: self.role == self.Role.RECIPIENT)
    is_driver = property(lambda self: self.role == self.Role.DRIVER)
    is_party = property(lambda self: self.role in (self.Role.SENDER, self.Role.RECIPIENT))


class RoleProfile(models.Model):

    ROLE = None
    # domyślny adres (nadawca: skąd odbierać, odbiorca: dokąd dowozić, kierowca: baza)
    address = models.CharField("adres domyślny", max_length=255, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.role = self.ROLE
        super().save(*args, **kwargs)

    @property
    def point(self):
        return (self.lat, self.lng) if self.lat is not None and self.lng is not None else None


class Sender(RoleProfile, User):
    ROLE = User.Role.SENDER
    company = models.CharField("firma", max_length=120, blank=True)


class Recipient(RoleProfile, User):
    ROLE = User.Role.RECIPIENT


class Driver(RoleProfile, User):
    ROLE = User.Role.DRIVER
    vehicle_name = models.CharField("pojazd", max_length=80, blank=True)
    vehicle_capacity_kg = models.DecimalField("ładowność [kg]", max_digits=7, decimal_places=1, default=500)

    @property
    def active_route(self):
        return self.routes.filter(status=Route.Status.ACTIVE).first()


ROLE_MODELS = {User.Role.SENDER: Sender, User.Role.RECIPIENT: Recipient, User.Role.DRIVER: Driver}


def _token_key():
    return secrets.token_hex(20)


class ApiToken(models.Model):
    """Token logowania do REST API (nagłówek `Authorization: Token <klucz>`).

    """
    key = models.CharField(max_length=40, unique=True, default=_token_key, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Token {self.user} ({self.created_at:%Y-%m-%d})"


# =============================================================================
#  Paczki
# =============================================================================
def _tracking_code():
    return "TX" + secrets.token_hex(4).upper()


class Package(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Oczekuje na kuriera"
        NEGOTIATING = "negotiating", "Negocjacja ekspresu"
        ASSIGNED = "assigned", "Przypisana do trasy"
        PICKED_UP = "picked_up", "W drodze"
        DELIVERED = "delivered", "Doręczona"
        CANCELLED = "cancelled", "Anulowana"

    tracking_code = models.CharField("numer przesyłki", max_length=12, unique=True, default=_tracking_code, editable=False)
    sender = models.ForeignKey(Sender, on_delete=models.PROTECT, related_name="sent_packages", verbose_name="nadawca")
    recipient = models.ForeignKey(Recipient, on_delete=models.PROTECT, related_name="received_packages",
                                  verbose_name="odbiorca")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    description = models.CharField("zawartość / opis", max_length=200, blank=True)
    weight_kg = models.DecimalField("waga [kg]", max_digits=7, decimal_places=2, default=1)

    pickup_address = models.CharField("adres odbioru", max_length=255)
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    pickup_contact = models.CharField("kontakt przy odbiorze", max_length=120, blank=True)

    delivery_address = models.CharField("adres doręczenia", max_length=255)
    delivery_lat = models.FloatField()
    delivery_lng = models.FloatField()
    delivery_contact = models.CharField("kontakt przy doręczeniu", max_length=120, blank=True)
    notes = models.TextField("uwagi dla kuriera", blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    driver = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name="packages")

    # cena – ustalana w negocjacji (ekspres) albo pusta dla zwykłej puli
    price = models.DecimalField("cena [zł]", max_digits=8, decimal_places=2, null=True, blank=True)
    sender_pays = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    recipient_pays = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tracking_code}: {self.pickup_address} → {self.delivery_address}"

    pickup_point = property(lambda self: (self.pickup_lat, self.pickup_lng))
    delivery_point = property(lambda self: (self.delivery_lat, self.delivery_lng))

    @property
    def is_active(self):
        return self.status not in (self.Status.DELIVERED, self.Status.CANCELLED)

    def is_party(self, user):
        return user.pk in (self.sender_id, self.recipient_id)

    @property
    def open_negotiation(self):
        return self.negotiations.filter(stage__in=Negotiation.OPEN_STAGES).first()



# =============================================================================
#  Trasy
# =============================================================================
class Route(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "W realizacji"
        DONE = "done", "Zakończona"
        REPLACED = "replaced", "Zastąpiona nową"

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="routes")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    shift_end = models.DateTimeField("koniec zmiany", null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    start_lat = models.FloatField()
    start_lng = models.FloatField()
    total_distance_m = models.FloatField(default=0)
    total_duration_s = models.FloatField(default=0)
    geometry = models.JSONField(default=dict, blank=True)
    matrix_source = models.CharField(max_length=10, default="osrm")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Trasa #{self.pk} – {self.driver} ({self.get_status_display()})"

    @property
    def remaining_shift_s(self):
        if not self.shift_end:
            return None
        return max(0.0, (self.shift_end - timezone.now()).total_seconds())

    def finish_if_done(self):
        if not self.stops.filter(completed_at__isnull=True).exists():
            self.status = self.Status.DONE
            self.finished_at = timezone.now()
            self.save(update_fields=["status", "finished_at"])
            return True
        return False


class RouteStop(models.Model):
    class Kind(models.TextChoices):
        PICKUP = "P", "Odbiór"
        DELIVERY = "D", "Doręczenie"

    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    order = models.PositiveIntegerField()
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="stops")
    kind = models.CharField(max_length=1, choices=Kind.choices)
    lat = models.FloatField()
    lng = models.FloatField()
    address = models.CharField(max_length=255)
    eta_s = models.FloatField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["route", "order"]
        unique_together = [("route", "order")]

    def __str__(self):
        return f"{self.order}. {self.get_kind_display()} {self.package.tracking_code}"

    @property
    def eta(self):
        return self.route.created_at + timedelta(seconds=self.eta_s)


# =============================================================================
#  Negocjacje: dorzucenie paczki do trwającej trasy (ekspres)
# =============================================================================
class Negotiation(models.Model):

    class Stage(models.TextChoices):
        PARTIES = "parties", "Negocjacje nadawcy i odbiorcy"
        DRIVER = "driver", "Decyzja kierowcy"
        CONFIRM = "confirm", "Potwierdzenie ceny kierowcy"
        ACCEPTED = "accepted", "Zaakceptowana – w trasie"
        REJECTED = "rejected", "Odrzucona"
        CANCELLED = "cancelled", "Wycofana"

    OPEN_STAGES = (Stage.PARTIES, Stage.DRIVER, Stage.CONFIRM)

    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="negotiations")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="negotiations")
    route = models.ForeignKey(Route, on_delete=models.SET_NULL, null=True, blank=True, related_name="negotiations")
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.PARTIES, db_index=True)

    # wycena algorytmu
    quoted_amount = models.DecimalField("cena algorytmu [zł]", max_digits=8, decimal_places=2)
    quote = models.JSONField("szczegóły wyceny", default=dict)

    # aktualne warunki
    amount = models.DecimalField("kwota [zł]", max_digits=8, decimal_places=2)
    sender_share_pct = models.PositiveSmallIntegerField(
        "udział nadawcy [%]", default=50, validators=[MinValueValidator(0), MaxValueValidator(100)])
    last_offer_role = models.CharField(max_length=10, choices=User.Role.choices)
    sender_ok = models.BooleanField(default=False)
    recipient_ok = models.BooleanField(default=False)
    party_rounds = models.PositiveSmallIntegerField(default=0)
    driver_counters = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["package"], condition=Q(stage__in=["parties", "driver", "confirm"]),
                                    name="one_open_negotiation_per_package"),
        ]

    def __str__(self):
        return f"Negocjacja #{self.pk} {self.package.tracking_code} ({self.get_stage_display()})"

    @property
    def is_open(self):
        return self.stage in self.OPEN_STAGES

    @property
    def recipient_share_pct(self):
        return 100 - self.sender_share_pct

    @property
    def sender_amount(self):
        return (self.amount * Decimal(self.sender_share_pct) / 100).quantize(Decimal("0.01"))

    @property
    def recipient_amount(self):
        return self.amount - self.sender_amount


class NegotiationEvent(models.Model):
    """Historia negocjacji – każdy krok pipeline'u zapisany jako zdarzenie."""

    class Action(models.TextChoices):
        QUOTE = "quote", "Wycena algorytmu"
        OPEN = "open", "Rozpoczęcie negocjacji"
        COUNTER = "counter", "Kontroferta"
        ACCEPT = "accept", "Akceptacja"
        CONFIRM = "confirm", "Potwierdzenie"
        REJECT = "reject", "Odrzucenie"
        CANCEL = "cancel", "Wycofanie"
        ADDED = "added", "Dodano do trasy"

    negotiation = models.ForeignKey(Negotiation, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=10, blank=True)  # sender/recipient/driver/system
    action = models.CharField(max_length=10, choices=Action.choices)
    amount = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    sender_share_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    stage_after = models.CharField(max_length=10, choices=Negotiation.Stage.choices)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    @property
    def role_label(self):
        return dict(User.Role.choices).get(self.role, "System")
