"""
operators.py — Operatory genetyczne dla problemu komiwojażera (TSP).

Operatory zawarte w module:
  * ``validate_route``             — sprawdzenie poprawności trasy O(n)
  * ``route_distance``             — suma kosztów krawędzi w cyklu
  * ``initial_population``         — losowa inicjalizacja populacji
  * ``tournament_select``          — selekcja k-turniejowa
  * ``ordered_crossover``          — krzyżowanie OX (zachowuje kolejność miast)
  * ``swap_mutation``              — mutacja przez zamianę dwóch miast
  * ``two_opt_delta``              — ocena ruchu 2-opt w O(1)
  * ``random_two_opt_improvement`` — losowe przeszukiwanie sąsiedztwa 2-opt
"""

from __future__ import annotations

import random
from collections import Counter

from tsp_ga.models import DistanceMatrix, Individual, Route


# -- Walidacja i koszt trasy --
def validate_route(route: Route, n: int) -> None:
    """Rzuć ``ValueError`` jeśli *route* nie jest poprawną permutacją 0..n-1."""
    if len(route) != n:
        raise ValueError(
            f"Nieprawidłowa długość trasy TSP: oczekiwano {n}, otrzymano {len(route)}"
        )

    counts = Counter(route)
    expected = set(range(n))
    actual = set(counts.keys())

    if actual != expected or any(count != 1 for count in counts.values()):
        missing = sorted(expected - actual)
        duplicates = sorted(city for city, count in counts.items() if count > 1)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "Nieprawidłowa permutacja trasy TSP: "
            f"brakujące={missing}, duplikaty={duplicates}, nieoczekiwane={unexpected}"
        )


def validate_route_if_enabled(route: Route, n: int, enabled: bool) -> None:
    """Waliduj trasę tylko gdy *enabled* jest True (tryb debug_routes)."""
    if enabled:
        validate_route(route, n)


def route_distance(route: Route, dist: DistanceMatrix) -> float:
    """Oblicz łączny dystans trasy cyklicznej (ostatnie miasto → pierwsze)."""
    total = 0.0
    for i in range(len(route) - 1):
        total += dist[route[i]][route[i + 1]]
    total += dist[route[-1]][route[0]]
    return total


# -- Konstrukcja osobników --
def random_route(n: int, rng: random.Random) -> Route:
    """Wygeneruj losową trasę jako permutację miast 0..n-1."""
    route = list(range(n))
    rng.shuffle(route)
    return route


def make_individual(route: Route, dist: DistanceMatrix) -> Individual:
    """Utwórz osobnika z podanej trasy, obliczając jego koszt."""
    return Individual(route=route, distance=route_distance(route, dist))


# -- Inicjalizacja populacji --
def initial_population(
    pop_size: int, n: int, dist: DistanceMatrix, rng: random.Random
) -> list[Individual]:
    """Utwórz losową populację *pop_size* osobników dla *n* miast."""
    return [make_individual(random_route(n, rng), dist) for _ in range(pop_size)]


# -- Selekcja i krzyżowanie --
def tournament_select(pop: list[Individual], k: int, rng: random.Random) -> Individual:
    """Wybierz najlepszego osobnika spośród *k* losowo wybranych kandydatów."""
    candidates = rng.sample(pop, k)
    return min(candidates, key=lambda ind: ind.distance)


def ordered_crossover(parent_a: Route, parent_b: Route, rng: random.Random) -> Route:
    """
    Krzyżowanie OX (Ordered Crossover) — zachowuje względną kolejność miast.

    Pobiera losowy wycinek z rodzica A, uzupełnia brakujące miasta
    w kolejności z rodzica B. Gwarantuje brak duplikatów.
    """
    n = len(parent_a)
    left, right = sorted(rng.sample(range(n), 2))

    child: list[int | None] = [None] * n
    child[left : right + 1] = parent_a[left : right + 1]

    used = {x for x in child if x is not None}
    insert_pos = (right + 1) % n

    for gene in parent_b[right + 1 :] + parent_b[: right + 1]:
        if gene not in used:
            child[insert_pos] = gene
            used.add(gene)
            insert_pos = (insert_pos + 1) % n

    result = [int(x) for x in child]
    validate_route(result, n)
    return result


# -- Mutacja --
def swap_mutation(route: Route, mutation_rate: float, rng: random.Random) -> None:
    """Zamień dwa losowe miasta w trasie z prawdopodobieństwem *mutation_rate*."""
    if rng.random() < mutation_rate:
        i, j = rng.sample(range(len(route)), 2)
        route[i], route[j] = route[j], route[i]


# -- Poprawa 2-opt --
def two_opt_delta(route: Route, dist: DistanceMatrix, i: int, j: int) -> float:
    """Oblicz zmianę kosztu po odwróceniu odcinka route[i:j] w O(1)."""
    a = route[i - 1]
    b = route[i]
    c = route[j - 1]
    d = route[j % len(route)]
    return dist[a][c] + dist[b][d] - dist[a][b] - dist[c][d]


def apply_two_opt_in_place(route: Route, i: int, j: int) -> None:
    """Odwróć odcinek route[i:j] w miejscu (wykonuje ruch 2-opt)."""
    route[i:j] = reversed(route[i:j])


def random_two_opt_improvement(
    route: Route, dist: DistanceMatrix, max_attempts: int, rng: random.Random
) -> Route:
    """
    Wykonaj do *max_attempts* losowych ulepszeń 2-opt.

    Każda próba ocenia zmianę kosztu w O(1) przy użyciu two_opt_delta.
    Zwraca kopię trasy (być może ulepszoną).
    """
    best = route[:]
    n = len(best)

    # Trasa krótsza niż 4 miasta nie daje sensu dla 2-opt.
    if n < 4 or max_attempts <= 0:
        return best

    for _ in range(max_attempts):
        i = rng.randrange(1, n - 2)
        j = rng.randrange(i + 2, n)
        if two_opt_delta(best, dist, i, j) < 0.0:
            apply_two_opt_in_place(best, i, j)

    return best
