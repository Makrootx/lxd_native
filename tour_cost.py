#!/usr/bin/env python3
"""
tour_cost.py — oblicza koszt trasy z pliku .opt.tour dla danej instancji .tsp.

Użycie:
    python tour_cost.py <plik.tsp> <plik.opt.tour>

Przykład:
    python tour_cost.py berlin52.tsp berlin52.opt.tour
"""

import sys
from pathlib import Path

from utils.config_utils import load_distance_matrix_from_tsp


def parse_opt_tour(path: str | Path) -> list[str]:
    """
    Wczytaj listę miast z pliku TSPLIB .opt.tour.

    Zwraca listę identyfikatorów miast w kolejności trasy (bez powrotu).
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    in_tour = False
    tour: list[str] = []

    for raw in lines:
        line = raw.strip()
        if line == "TOUR_SECTION":
            in_tour = True
            continue
        if not in_tour:
            continue
        if line in {"-1", "EOF", ""}:
            break
        tour.append(line)

    if not tour:
        raise ValueError(f"Brak danych w TOUR_SECTION w pliku {path}")

    return tour


def tour_cost(matrix, tour: list[str]) -> float:
    """Oblicz sumaryczny koszt trasy (ostatnie miasto → pierwsze domykają pętlę)."""
    total = 0.0
    n = len(tour)
    for i in range(n):
        a = tour[i]
        b = tour[(i + 1) % n]
        total += matrix.distance(a, b)
    return total


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Użycie: {sys.argv[0]} <plik.tsp> <plik.opt.tour>", file=sys.stderr)
        sys.exit(1)

    tsp_path, tour_path = sys.argv[1], sys.argv[2]

    matrix = load_distance_matrix_from_tsp(tsp_path)
    tour = parse_opt_tour(tour_path)

    if len(tour) != matrix.size:
        raise ValueError(f"Trasa zawiera {len(tour)} miast, instancja ma {matrix.size}")

    cost = tour_cost(matrix, tour)

    print(f"Plik TSP  : {tsp_path}")
    print(f"Trasa     : {tour_path}")
    print(f"Miasta    : {matrix.size}")
    print(f"Koszt     : {cost:.2f}")


if __name__ == "__main__":
    main()
