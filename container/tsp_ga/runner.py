"""
runner.py — Uruchamianie wyspy GA.

Funkcja run_island() realizuje jedną rundę ewolucji na wyspie.
Obsługuje ciągłość populacji (initial_pop) i imigrację (immigrant_routes),
co umożliwia wielorundowy model z migracją sterowaną przez orkiestratora.

Przebieg wielorundowy:
  Runda 1: wszystkie wyspy startują z losową populacją, ewoluują migration_interval generacji.
  Runda 2: orkiestrator dobiera imigrantów wg topologii, wyspy kontynuują
            z poprzednią populacją i imigrantami wstrzykniętymi przed ewolucją.
  ...
  Runda N: ostatni fragment generacji, zbieranie wyników końcowych.

run_island() zwraca (IslandResult, final_population_routes) — lista tras
końcowej populacji jest przekazywana jako initial_pop w następnej rundzie.
"""

from __future__ import annotations

import heapq
import random

from tsp_ga.evolution import best_individual, evolve_one_generation
from tsp_ga.models import GAConfig, History, IslandResult, Problem, Route
from tsp_ga.operators import initial_population, make_individual, validate_route
from tsp_ga.timing import StageTimer


# -- Główna funkcja ewolucji wyspy --
def run_island(
    ga_config: GAConfig,
    rng_seed: int,
    problem: Problem,
    timer: StageTimer,
    initial_pop: list[Route] | None = None,
    immigrant_routes: list[Route] | None = None,
) -> tuple[IslandResult, list[Route]]:
    """
    Uruchom jedną wyspę GA na *ga_config.generations* generacji.

    Parametry
    ---------
    ga_config        : pełna konfiguracja GA dla tej rundy
    rng_seed         : deterministyczny seed generatora losowego dla tej wyspy
    problem          : definicja instancji TSP (miasta i macierz odległości)
    timer            : StageTimer do pomiaru czasu czystej ewolucji
    initial_pop      : trasy populacji do kontynuacji (z poprzedniej rundy).
                       Gdy None — generowana jest losowa populacja startowa.
    immigrant_routes : trasy imigrantów z innej wyspy (migracja).
                       Wstrzykiwane przed ewolucją: łączone z initial_pop,
                       najlepsze pop_size osobników zostaje zachowanych.

    Zwraca
    ------
    ``(IslandResult, final_population_routes)``
    Drugi element to lista tras końcowej populacji — przekaż jako
    ``initial_pop`` w następnej rundzie.
    """
    rng = random.Random(rng_seed)
    n_cities = len(problem.cities)

    # -- Budowanie populacji startowej --
    if initial_pop is not None:
        pop = [make_individual(route, problem.distances) for route in initial_pop]
    else:
        pop = initial_population(ga_config.population, n_cities, problem.distances, rng)

    # -- Wstrzykiwanie imigrantów --
    # Łączymy imigrantów z bieżącą populacją i zachowujemy najlepsze pop_size
    # osobników (identyczna logika jak w strategiach migracji orkiestratora).
    if immigrant_routes:
        immigrants = [make_individual(r, problem.distances) for r in immigrant_routes]
        combined = pop + immigrants
        pop = heapq.nsmallest(
            ga_config.population, combined, key=lambda ind: ind.distance
        )

    best_seen = best_individual(pop)
    history: History = []
    evolution_time_seconds = 0.0

    if ga_config.debug_routes:
        for individual in pop:
            validate_route(individual.route, n_cities)

    # -- Pętla ewolucyjna --
    for generation in range(1, ga_config.generations + 1):
        # Przechwycenie argumentów przez domyślne wartości zapobiega
        # problemom z późnym wiązaniem zmiennych w domknięciu.
        def _evolve(p=pop, d=problem.distances, c=ga_config, r=rng):
            return evolve_one_generation(pop=p, dist=d, config=c, rng=r)

        pop_obj, elapsed = timer.measure(_evolve)
        pop = pop_obj
        evolution_time_seconds += elapsed

        if ga_config.debug_routes:
            for individual in pop:
                validate_route(individual.route, n_cities)

        current_best = best_individual(pop)
        if current_best.distance < best_seen.distance:
            best_seen = current_best

        # Zapisuj punkt historii co report_interval generacji lub na końcu rundy.
        if (
            generation % ga_config.report_interval == 0
            or generation == ga_config.generations
        ):
            history.append((generation, best_seen.distance))

    # -- Budowanie wyniku --
    result = IslandResult(
        best_distance=best_seen.distance,
        best_route=best_seen.route,
        history=history,
        migration_count=0,  # zliczane przez orkiestratora
        migration_time_seconds=0.0,  # zliczane przez orkiestratora
        evolution_time_seconds=evolution_time_seconds,
    )

    return result, [ind.route for ind in pop]
