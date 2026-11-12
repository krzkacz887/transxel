"""
Planowanie trasy kuriera – problem odbioru i dostawy (Pickup and Delivery Problem).

Kurier nie wozi paczek do magazynu: odbiera paczkę u nadawcy i dowozi ją
bezpośrednio do odbiorcy w ramach jednej trasy. Ograniczenia:

* odbiór (P) danej paczki musi być przed jej doręczeniem (D),
* w żadnym momencie ładunek nie może przekroczyć ładowności pojazdu,
* łączny czas trasy (przejazdy + postoje) nie może przekroczyć długości zmiany,
* paczki "obowiązkowe" (już w aucie lub już przypisane kierowcy) muszą być w trasie,
* paczki "opcjonalne" (z puli) dobierane są tylko, gdy opłaca się je wziąć "po drodze".

Algorytm:
1. Najtańsze wstawianie (cheapest insertion) – najpierw zadania obowiązkowe,
   potem w pętli opcjonalne: zawsze to, które najmniej wydłuża trasę.
2. Przeszukiwanie lokalne (relocate) – każdą paczkę (parę P+D) wyjmujemy
   i wstawiamy w najlepsze miejsce; powtarzamy, dopóki trasa się skraca.
   Zaoszczędzony czas wykorzystujemy na dobranie kolejnych paczek.

Moduł nie zależy od Django – działa na macierzy czasów przejazdu (sekundy),
więc łatwo go testować i podmienić źródło danych.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Optional, Sequence

PICKUP = "P"
DELIVERY = "D"
EPS = 1e-6


@dataclass
class Job:
    """Jedna paczka do obsłużenia.

    pickup  – indeks węzła odbioru w macierzy; None = paczka już jest w aucie
    delivery – indeks węzła doręczenia
    """

    key: Hashable
    delivery: int
    pickup: Optional[int] = None
    weight: float = 0.0
    mandatory: bool = False

    @property
    def onboard(self) -> bool:
        return self.pickup is None


@dataclass
class PlannedStop:
    job_key: Hashable
    kind: str  # PICKUP / DELIVERY
    node: int
    arrival_s: float  # skumulowany czas dojazdu od startu (bez postoju na tym przystanku)


@dataclass
class Plan:
    stops: list[PlannedStop] = field(default_factory=list)
    total_duration_s: float = 0.0
    served: list[Hashable] = field(default_factory=list)
    unserved: list[Hashable] = field(default_factory=list)


class _Router:
    def __init__(
        self,
        duration: Sequence[Sequence[float]],
        jobs: Sequence[Job],
        start: int,
        end: Optional[int],
        capacity: float,
        max_duration: Optional[float],
        service_time: float,
        max_jobs: Optional[int],
    ):
        self.d = duration
        self.jobs = list(jobs)
        self.start = start
        self.end = end
        self.capacity = capacity if capacity and capacity > 0 else float("inf")
        self.max_duration = max_duration if max_duration and max_duration > 0 else float("inf")
        self.service = service_time
        self.max_jobs = max_jobs
        # trasa: lista (indeks_zadania, rodzaj)
        self.route: list[tuple[int, str]] = []

    # ------------------------------------------------------------------ utils
    def node(self, stop: tuple[int, str]) -> int:
        j = self.jobs[stop[0]]
        return j.pickup if stop[1] == PICKUP else j.delivery

    def dist(self, a: Optional[int], b: Optional[int]) -> float:
        if a is None or b is None:  # otwarty koniec trasy
            return 0.0
        return float(self.d[a][b])

    def _nodes(self, route):
        return [self.node(s) for s in route]

    def cost(self, route=None) -> float:
        route = self.route if route is None else route
        prev = self.start
        total = 0.0
        for s in route:
            n = self.node(s)
            total += self.dist(prev, n) + self.service
            prev = n
        total += self.dist(prev, self.end)
        return total

    def _gap_loads(self, route) -> list[float]:
        """gap_load[g] = ładunek na odcinku wjeżdżającym do przystanku g (g = 0..n)."""
        load = sum(self.jobs[i].weight for i, k in route if k == DELIVERY and self.jobs[i].onboard)
        loads = [load]
        for i, k in route:
            w = self.jobs[i].weight
            load += w if k == PICKUP else -w
            loads.append(load)
        return loads

    def jobs_in_route(self) -> set[int]:
        return {i for i, _ in self.route}

    # -------------------------------------------------------------- insertion
    def best_insertion(self, ji: int, route=None, check_duration=True, check_capacity=True):
        """Zwraca (delta, gap_p, gap_d) najtańszego wstawienia zadania ji lub None."""
        route = self.route if route is None else route
        job = self.jobs[ji]
        nodes = self._nodes(route)
        n = len(route)
        prev_of = lambda g: self.start if g == 0 else nodes[g - 1]  # noqa: E731
        next_of = lambda g: self.end if g == n else nodes[g]  # noqa: E731
        loads = self._gap_loads(route)
        base = self.cost(route) if check_duration else 0.0
        cap = self.capacity if check_capacity else float("inf")
        w = job.weight
        D = job.delivery
        svc2 = self.service * (1 if job.onboard else 2)
        best = None

        def gap_delta(g, x):
            a, b = prev_of(g), next_of(g)
            return self.dist(a, x) + self.dist(x, b) - self.dist(a, b)

        d_deltas = [gap_delta(g, D) for g in range(n + 1)]

        if job.onboard:
            # paczka jest w aucie: od startu do doręczenia zajmuje miejsce
            running = -float("inf")
            for g in range(n + 1):
                running = max(running, loads[g])
                if running + w > cap + EPS:
                    break
                delta = d_deltas[g] + svc2
                if check_duration and base + delta > self.max_duration + EPS:
                    continue
                if best is None or delta < best[0]:
                    best = (delta, None, g)
            return best

        P = job.pickup
        for gp in range(n + 1):
            p_delta = gap_delta(gp, P)
            running = -float("inf")
            for gd in range(gp, n + 1):
                running = max(running, loads[gd])
                if running + w > cap + EPS:
                    break
                if gd == gp:
                    a, b = prev_of(gp), next_of(gp)
                    delta = self.dist(a, P) + self.dist(P, D) + self.dist(D, b) - self.dist(a, b)
                else:
                    delta = p_delta + d_deltas[gd]
                delta += svc2
                if check_duration and base + delta > self.max_duration + EPS:
                    continue
                if best is None or delta < best[0]:
                    best = (delta, gp, gd)
        return best

    @staticmethod
    def apply_insertion(route, ji, gp, gd):
        route = list(route)
        if gp is None:
            route.insert(gd, (ji, DELIVERY))
        else:
            # najpierw D (dalej), potem P – indeksy luk dotyczą trasy oryginalnej
            route.insert(gd, (ji, DELIVERY))
            route.insert(gp, (ji, PICKUP))
        return route

    def insert_mandatory(self):
        order = sorted(
            (i for i, j in enumerate(self.jobs) if j.mandatory),
            key=lambda i: (not self.jobs[i].onboard, str(self.jobs[i].key)),
        )
        for ji in order:
            ins = self.best_insertion(ji, check_duration=False)
            if ins is None:
                # brak miejsca przy ograniczeniach – zadanie i tak musi zostać obsłużone
                ins = self.best_insertion(ji, check_duration=False, check_capacity=False)
            _, gp, gd = ins
            self.route = self.apply_insertion(self.route, ji, gp, gd)

    def _optional_count(self):
        return sum(1 for i in self.jobs_in_route() if not self.jobs[i].mandatory)

    def insert_optional(self) -> bool:
        changed = False
        while True:
            if self.max_jobs is not None and self._optional_count() >= self.max_jobs:
                return changed
            in_route = self.jobs_in_route()
            best = None
            for ji, job in enumerate(self.jobs):
                if job.mandatory or ji in in_route:
                    continue
                ins = self.best_insertion(ji)
                if ins and (best is None or ins[0] < best[1][0]):
                    best = (ji, ins)
            if best is None:
                return changed
            ji, (_, gp, gd) = best
            self.route = self.apply_insertion(self.route, ji, gp, gd)
            changed = True

    # ----------------------------------------------------------- local search
    def relocate_pass(self) -> bool:
        improved = False
        current = self.cost()
        for ji in list(self.jobs_in_route()):
            without = [s for s in self.route if s[0] != ji]
            ins = self.best_insertion(ji, route=without, check_duration=False)
            if ins is None:
                continue
            candidate = self.apply_insertion(without, ji, ins[1], ins[2])
            c = self.cost(candidate)
            if c < current - 1e-3:
                self.route, current = candidate, c
                improved = True
        return improved

    def solve(self, max_rounds: int = 50):
        self.insert_mandatory()
        self.insert_optional()
        for _ in range(max_rounds):
            a = self.relocate_pass()
            b = self.insert_optional()
            if not (a or b):
                break


def plan_route(
    duration: Sequence[Sequence[float]],
    jobs: Sequence[Job],
    start: int = 0,
    end: Optional[int] = None,
    capacity: float = 0,
    max_duration: Optional[float] = None,
    service_time: float = 0,
    max_jobs: Optional[int] = None,
) -> Plan:
    """Planuje trasę. `end=None` – trasa otwarta (kurier kończy na ostatnim doręczeniu)."""
    r = _Router(duration, jobs, start, end, capacity, max_duration, service_time, max_jobs)
    r.solve()

    plan = Plan()
    t, prev = 0.0, start
    for ji, kind in r.route:
        n = r.node((ji, kind))
        t += r.dist(prev, n)
        plan.stops.append(PlannedStop(job_key=jobs[ji].key, kind=kind, node=n, arrival_s=t))
        t += service_time
        prev = n
    t += r.dist(prev, end)
    plan.total_duration_s = t
    served = r.jobs_in_route()
    plan.served = [jobs[i].key for i in sorted(served)]
    plan.unserved = [j.key for i, j in enumerate(jobs) if i not in served]
    return plan


@dataclass
class InsertionResult:
    feasible: bool
    reason: str = ""
    delta_duration_s: float = 0.0      # o ile wydłuży się trasa (z postojami)
    delta_distance: float = 0.0        # o ile wydłuży się dystans (wg macierzy distance)
    base_duration_s: float = 0.0
    new_sequence: list = field(default_factory=list)  # [(job_key, kind), ...]


def evaluate_insertion(
    duration: Sequence[Sequence[float]],
    jobs: Sequence[Job],
    sequence: Sequence[tuple[Hashable, str]],
    new_job: Job,
    start: int = 0,
    capacity: float = 0,
    max_duration: Optional[float] = None,
    service_time: float = 0,
    distance: Optional[Sequence[Sequence[float]]] = None,
) -> InsertionResult:
    """Koszt dorzucenia `new_job` do ISTNIEJĄCEJ kolejności przystanków (bez jej zmieniania).

    Używane do wyceny „ekspresu”: kierowca jest w trasie, inne przystanki zostają
    w swojej kolejności, a nowa paczka wchodzi w najtańsze miejsce.
    """
    all_jobs = list(jobs) + [new_job]
    idx = {j.key: i for i, j in enumerate(all_jobs)}
    r = _Router(duration, all_jobs, start, None, capacity, max_duration, service_time, None)
    r.route = [(idx[k], kind) for k, kind in sequence]
    base = r.cost()
    new_i = len(all_jobs) - 1

    ins = r.best_insertion(new_i)
    if ins is None:
        if r.best_insertion(new_i, check_duration=False) is not None:
            reason = "Nie zmieści się w pozostałym czasie zmiany kierowcy."
        elif r.best_insertion(new_i, check_duration=False, check_capacity=False) is not None:
            reason = "Brak miejsca w aucie (ładowność) na odcinku, gdzie paczka musiałaby jechać."
        else:
            reason = "Nie da się wstawić paczki do trasy."
        return InsertionResult(feasible=False, reason=reason, base_duration_s=base)

    delta, gp, gd = ins
    new_route = r.apply_insertion(r.route, new_i, gp, gd)
    d_dist = 0.0
    if distance is not None:
        def route_dist(route):
            prev, tot = start, 0.0
            for s in route:
                n = r.node(s)
                tot += float(distance[prev][n])
                prev = n
            return tot
        d_dist = route_dist(new_route) - route_dist(r.route)
    return InsertionResult(
        feasible=True, delta_duration_s=delta, delta_distance=d_dist, base_duration_s=base,
        new_sequence=[(all_jobs[i].key, k) for i, k in new_route],
    )


def validate_plan(plan: Plan, jobs: Sequence[Job], capacity: float) -> list[str]:
    """Sprawdza poprawność planu (używane w testach)."""
    errors = []
    by_key = {j.key: j for j in jobs}
    load = sum(by_key[s.job_key].weight for s in plan.stops if s.kind == DELIVERY and by_key[s.job_key].onboard)
    seen_p = set()
    for s in plan.stops:
        j = by_key[s.job_key]
        if s.kind == PICKUP:
            seen_p.add(s.job_key)
            load += j.weight
        else:
            if not j.onboard and s.job_key not in seen_p:
                errors.append(f"doręczenie {s.job_key} przed odbiorem")
            load -= j.weight
        if capacity and load > capacity + EPS:
            errors.append(f"przekroczona ładowność przy {s.job_key}: {load}")
    return errors

