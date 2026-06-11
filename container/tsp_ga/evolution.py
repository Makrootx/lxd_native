"""
evolution.py — Ewolucja jednej generacji populacji wyspy GA.

Implementuje pełny cykl jednej generacji:
  1. Kopiowanie elit (nsmallest — O(n log k) zamiast pełnego sortowania).
  2. Selekcja turniejowa → krzyżowanie OX → mutacja swap → poprawa 2-opt.
"""

from __future__ import annotations

import heapq
import random

from tsp_ga.models import DistanceMatrix, GAConfig, Individual
from tsp_ga.operators import (
    make_individual,
    ordered_crossover,
    random_two_opt_improvement,
    swap_mutation,
    tournament_select,
    validate_route_if_enabled,
)


# -- Funkcje pomocnicze selekcji --
def best_individual(pop: list[Individual]) -> Individual:
    """Zwróć osobnika z najniższym kosztem trasy w populacji."""
    return min(pop, key=lambda ind: ind.distance)


def select_elite(pop: list[Individual], elite_count: int) -> list[Individual]:
    """Wybierz *elite_count* najlepszych osobników z populacji (heapq.nsmallest)."""
    return heapq.nsmallest(elite_count, pop, key=lambda ind: ind.distance)


# -- Ewolucja jednej generacji --
def evolve_one_generation(
    pop: list[Individual],
    dist: DistanceMatrix,
    config: GAConfig,
    rng: random.Random,
) -> list[Individual]:
    """
    Wygeneruj następną generację populacji.

    Kroki:
      1. Skopiuj elity (heapq.nsmallest — brak pełnego sortowania).
      2. Uzupełnij populację potomkami: selekcja turniejowa → OX → mutacja swap
         → opcjonalna poprawa 2-opt.
    """
    pop_size = len(pop)
    n = len(dist)
    new_pop = select_elite(pop, config.elite)

    while len(new_pop) < pop_size:
        parent_a = tournament_select(pop, config.tournament, rng)
        parent_b = tournament_select(pop, config.tournament, rng)

        validate_route_if_enabled(parent_a.route, n, config.debug_routes)
        validate_route_if_enabled(parent_b.route, n, config.debug_routes)

        child_route = ordered_crossover(parent_a.route, parent_b.route, rng)
        validate_route_if_enabled(child_route, n, config.debug_routes)

        swap_mutation(child_route, config.mutation, rng)
        validate_route_if_enabled(child_route, n, config.debug_routes)

        if config.two_opt_attempts > 0:
            child_route = random_two_opt_improvement(
                child_route, dist, config.two_opt_attempts, rng
            )
            validate_route_if_enabled(child_route, n, config.debug_routes)

        new_pop.append(make_individual(child_route, dist))

    return new_pop
