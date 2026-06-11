"""
models.py — Modele danych dla wyspowego algorytmu genetycznego (GA).

Zawiera typy danych i struktury używane przez moduł tsp_ga, w tym:
  * Individual — reprezentacja pojedynczego osobnika (trasa + dystans)
  * Problem — definicja instancji TSP (lista miast + macierz odległości)
  * IslandResult — wynik jednej wyspy po zakończeniu ewolucji
  * GAConfig — konfiguracja parametrów algorytmu genetycznego dla jednej rundy
"""

from __future__ import annotations

from dataclasses import dataclass

# -- Aliasy typów --
# Współrzędna miasta: para (x, y)
City = tuple[float, float]

# Trasa: lista indeksów miast (permutacja 0..n-1)
Route = list[int]

# Macierz odległości: dwuwymiarowa lista float
DistanceMatrix = list[list[float]]

# Historia najlepszego dystansu: lista (generacja, dystans)
History = list[tuple[int, float]]


# -- Modele danych --
@dataclass(slots=True)
class Individual:
    """Pojedynczy osobnik populacji: trasa + jej koszt."""

    route: Route
    distance: float


@dataclass(slots=True)
class Problem:
    """Definicja instancji TSP: lista miast i macierz odległości."""

    cities: list[City]
    distances: DistanceMatrix


@dataclass(slots=True)
class IslandResult:
    """Wynik jednej wyspy po zakończeniu ewolucji."""

    best_distance: float  # najlepszy znaleziony dystans
    best_route: Route  # najlepsza znaleziona trasa
    history: History  # historia poprawy w kolejnych generacjach
    migration_count: int  # liczba rund migracyjnych (zliczana przez orkiestratora)
    migration_time_seconds: float  # czas migracji (zliczany przez orkiestratora)
    evolution_time_seconds: float  # czas czystej ewolucji


@dataclass(slots=True)
class GAConfig:
    """
    Konfiguracja jednej rundy GA na wyspie.

    Zawiera wyłącznie parametry używane przez operatory ewolucji.
    Parametry orkiestratora (strategia migracji, interwał migracji)
    są obsługiwane przez mastera i nigdy nie trafiają do pracownika.
    """

    population: int  # rozmiar populacji na wyspie
    generations: int  # liczba generacji do wykonania w tej rundzie
    mutation: float  # prawdopodobieństwo mutacji swap
    elite: int  # liczba elit kopiowanych bez zmian do następnej generacji
    tournament: int  # rozmiar turnieju selekcji
    two_opt_attempts: int  # liczba losowych prób poprawy 2-opt na dziecko
    report_interval: int  # co ile generacji zapisywać historię
    debug_routes: bool  # czy włączyć walidację poprawności tras (kosztowne)
