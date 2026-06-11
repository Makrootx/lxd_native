#!/usr/bin/env python3
"""
worker.py — Punkt wejścia kontenera LXD dla wyspowego GA (TSP).

Odczytuje plik /root/task.json, uruchamia algorytm genetyczny na wyspie
i wypisuje wynik w formacie JSON na standardowe wyjście.

Model wielorundowy (sterowany przez orkiestratora)
--------------------------------------------------
Orkiestrator może uruchamiać wiele rund przez dodanie pól w task.json:

  initial_population  list[list[int]]  — populacja do kontynuacji
                                         (trasy jako listy indeksów miast)
  immigrant_routes    list[list[int]]  — elitarne trasy z innej wyspy,
                                         wstrzykiwane przed tą rundą
  immigrants          int              — ilu imigrantów wysłać w odpowiedzi

Pracownik zawsze zwraca:
  elite_routes        list[list[int]]  — top-k tras wg dystansu
  elite_distances     list[float]      — odpowiadające dystanse
  final_population    list[list[int]]  — pełna populacja końcowa
                                         (przekaż jako initial_population
                                          w następnej rundzie)
"""

import heapq
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tsp_ga.models import GAConfig, Problem
from tsp_ga.operators import make_individual
from tsp_ga.runner import run_island
from tsp_ga.timing import StageTimer

# Ścieżka do pliku z zadaniem wstrzykniętego przez orkiestratora.
TASK_PATH = "/root/task.json"


# -- Wczytywanie zadania --
def load_task(path: str) -> dict:
    """Wczytaj i zwróć słownik zadania z pliku JSON."""
    with open(path) as fh:
        return json.load(fh)


# -- Budowanie instancji TSP --
def build_problem(task: dict) -> tuple[Problem, list[str]]:
    """
    Zbuduj obiekt Problem z danych zadania.

    Macierz odległości jest indeksowana liczbowo; nazwy miast przechowywane
    oddzielnie do mapowania wynikowej trasy na czytelne nazwy.
    """
    city_names: list[str] = task["city_names"]
    dist_matrix: list[list[float]] = task["distance_matrix"]
    # Pseudo-współrzędne (nieużywane w obliczeniach — liczy się macierz odległości).
    cities = [(float(i), 0.0) for i in range(len(city_names))]
    return Problem(cities=cities, distances=dist_matrix), city_names


# -- Konfiguracja GA --
def build_ga_config(task: dict) -> GAConfig:
    """
    Zbuduj GAConfig z danych zadania.

    Zawiera wyłącznie parametry używane przez operatory ewolucji.
    Parametry orkiestratora (migration_strategy, migration_interval) nie
    są tu obecne — orkiestrator obsługuje je przed wysyłką zadania.
    """
    return GAConfig(
        population=task.get("population_size", 50),
        generations=task.get("generations", 1000),
        mutation=task.get("mutation", 0.15),
        elite=task.get("elite", 2),
        tournament=task.get("tournament", 4),
        two_opt_attempts=task.get("two_opt_attempts", 3),
        report_interval=task.get("report_interval", 50),
        debug_routes=task.get("debug_routes", False),
    )


# -- Ekstrakcja elit --
def extract_elites(
    final_pop: list[list[int]],
    distances: list[list[float]],
    k: int,
) -> tuple[list[list[int]], list[float]]:
    """Zwróć top-k tras z populacji końcowej posortowanych wg dystansu."""
    if k <= 0:
        return [], []
    individuals = [make_individual(r, distances) for r in final_pop]
    elites = heapq.nsmallest(k, individuals, key=lambda ind: ind.distance)
    return [e.route for e in elites], [e.distance for e in elites]


# -- Punkt wejścia --
def main() -> None:
    task = load_task(TASK_PATH)
    problem, city_names = build_problem(task)
    ga_config = build_ga_config(task)

    seed = task.get("seed", 42)
    initial_pop = task.get("initial_population")  # list[list[int]] lub None
    immigrant_routes = task.get("immigrant_routes")  # list[list[int]] lub None
    immigrants_count = max(task.get("immigrants", 2), 1)

    timer = StageTimer(time.perf_counter)
    wall_start = time.perf_counter()

    result, final_pop = run_island(
        ga_config=ga_config,
        rng_seed=seed,
        problem=problem,
        timer=timer,
        initial_pop=initial_pop,
        immigrant_routes=immigrant_routes,
    )

    elapsed = time.perf_counter() - wall_start

    # Mapuj indeksy miast z powrotem na nazwy dla czytelności wyników.
    route_names = [city_names[i] for i in result.best_route]
    elite_routes, elite_distances = extract_elites(
        final_pop, problem.distances, immigrants_count
    )

    print(
        json.dumps(
            {
                "worker_id": socket.gethostname(),
                "distance": result.best_distance,
                "path": route_names,
                "elapsed_seconds": elapsed,
                "evolution_time_seconds": result.evolution_time_seconds,
                "migration_count": result.migration_count,
                "history": result.history,
                # -- Pola wspierające migrację --
                "elite_routes": elite_routes,  # elity do wysłania na inne wyspy
                "elite_distances": elite_distances,  # ich dystanse
                "final_population": final_pop,  # pełna populacja (kontynuacja)
            }
        )
    )


if __name__ == "__main__":
    main()
