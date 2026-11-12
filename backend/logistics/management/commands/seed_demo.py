"""Dane demonstracyjne: nadawcy, odbiorcy, kierowcy i paczki po Warszawie.

Użycie:  python manage.py seed_demo [--packages 20] [--reset] [--no-route]
Domyślnie kierowca1 dostaje od razu aktywną trasę – można testować ekspres i negocjacje.
"""
import random

from django.core.management.base import BaseCommand, CommandError

from logistics.models import Driver, Negotiation, Package, Recipient, Route, Sender, User
from logistics.services.planning import plan_for_driver

PLACES = [
    ("Warszawa, Pałac Kultury i Nauki", 52.2318, 21.0060),
    ("Warszawa, Dworzec Centralny", 52.2289, 21.0035),
    ("Warszawa, Rynek Starego Miasta", 52.2497, 21.0122),
    ("Warszawa, Łazienki Królewskie", 52.2152, 21.0355),
    ("Warszawa, Stadion Narodowy", 52.2395, 21.0458),
    ("Warszawa, Galeria Mokotów", 52.1800, 21.0030),
    ("Warszawa, Pałac w Wilanowie", 52.1650, 21.0900),
    ("Warszawa, Dworzec Wileński", 52.2546, 21.0350),
    ("Warszawa, Arkadia", 52.2570, 20.9840),
    ("Warszawa, Politechnika Warszawska", 52.2206, 21.0105),
    ("Warszawa, Uniwersytet Warszawski", 52.2403, 21.0189),
    ("Warszawa, Centrum Nauki Kopernik", 52.2419, 21.0287),
    ("Warszawa, Plac Zbawiciela", 52.2196, 21.0147),
    ("Warszawa, Rondo Daszyńskiego", 52.2302, 20.9840),
    ("Warszawa, Metro Kabaty", 52.1311, 21.0657),
    ("Warszawa, Lotnisko Chopina", 52.1657, 20.9671),
    ("Warszawa, Plac Wilsona", 52.2690, 20.9850),
    ("Warszawa, Służewiec – ul. Domaniewska", 52.1820, 21.0190),
    ("Warszawa, Gocław", 52.2290, 21.1050),
    ("Warszawa, Bemowo", 52.2400, 20.9100),
]
ITEMS = ["Dokumenty", "Książki", "Części rowerowe", "Elektronika", "Ubrania", "Zabawki", "Kosmetyki", "Obiad"]


class Command(BaseCommand):
    help = "Tworzy konta demo (nadawcy, odbiorcy, kierowcy) i przykładowe paczki w Warszawie."

    def add_arguments(self, parser):
        parser.add_argument("--packages", type=int, default=20)
        parser.add_argument("--reset", action="store_true", help="Usuń istniejące paczki, trasy i negocjacje")
        parser.add_argument("--no-route", action="store_true", help="Nie planuj trasy dla kierowca1")
        parser.add_argument("--seed", type=int, default=42)

    def _account(self, Model, username, password, place, **fields):
        account = Model.objects.filter(username=username).first()
        if account is None:
            if User.objects.filter(username=username).exists():
                raise CommandError(f"Użytkownik {username} istnieje, ale nie jest typu {Model.__name__}. Użyj nowej bazy.")
            account = Model(username=username)
            account.set_password(password)
        account.address, account.lat, account.lng = place
        for k, v in fields.items():
            setattr(account, k, v)
        account.save()
        return account

    def handle(self, *args, **opts):
        rnd = random.Random(opts["seed"])
        if opts["reset"]:
            Negotiation.objects.all().delete()
            Route.objects.all().delete()
            Package.objects.all().delete()
            self.stdout.write("Usunięto paczki, trasy i negocjacje.")

        senders = [
            self._account(Sender, "nadawca1", "demo1234", PLACES[0], first_name="Anna", last_name="Nowak",
                          company="Księgarnia Centrum", phone="500 100 200"),
            self._account(Sender, "nadawca2", "demo1234", PLACES[9], first_name="Piotr", last_name="Kowalski",
                          company="Rowery Mokotów", phone="500 300 400"),
        ]
        recipients = [
            self._account(Recipient, "odbiorca1", "demo1234", PLACES[4], first_name="Maria", last_name="Wiśniewska",
                          phone="510 111 222"),
            self._account(Recipient, "odbiorca2", "demo1234", PLACES[16], first_name="Jan", last_name="Wójcik",
                          phone="510 333 444"),
        ]
        drivers = [
            self._account(Driver, "kierowca1", "demo1234", PLACES[1], first_name="Tomasz", last_name="Lewandowski",
                          vehicle_name="Ford Transit", vehicle_capacity_kg=300, phone="600 111 222"),
            self._account(Driver, "kierowca2", "demo1234", PLACES[7], first_name="Kasia", last_name="Kamińska",
                          vehicle_name="Fiat Doblo", vehicle_capacity_kg=150, phone="600 333 444"),
        ]

        for _ in range(opts["packages"]):
            a, b = rnd.sample(PLACES, 2)
            j = lambda: rnd.uniform(-0.004, 0.004)  # noqa: E731
            sender, recipient = rnd.choice(senders), rnd.choice(recipients)
            Package.objects.create(
                sender=sender, recipient=recipient, created_by=rnd.choice([sender, recipient]),
                description=rnd.choice(ITEMS), weight_kg=round(rnd.uniform(0.5, 25), 1),
                pickup_address=a[0], pickup_lat=a[1] + j(), pickup_lng=a[2] + j(),
                delivery_address=b[0], delivery_lat=b[1] + j(), delivery_lng=b[2] + j())

        if not opts["no_route"] and not drivers[0].active_route:
            result = plan_for_driver(drivers[0], shift_hours=8, max_new=5)
            if result.route:
                self.stdout.write(f"kierowca1 jest w trasie: {result.route.stops.count()} przystanków "
                                  f"(źródło czasów: {result.matrix_source}).")

        self.stdout.write(self.style.SUCCESS(
            f"Gotowe: {opts['packages']} paczek. Hasło do wszystkich kont: demo1234\n"
            "  nadawcy:   nadawca1, nadawca2\n  odbiorcy:  odbiorca1, odbiorca2\n  kierowcy:  kierowca1, kierowca2"))
