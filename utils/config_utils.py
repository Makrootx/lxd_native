"""
config_utils.py — Klasy i funkcje pomocnicze dla macierzy odległości TSP.

Zawartość:
  * DistanceMatrix                  — symetryczna macierz odległości euklidesowych
                                      między nazwanymi miastami
  * generate_random_distance_matrix — generowanie losowych miast
  * load_distance_matrix_from_csv   — wczytywanie miast z pliku CSV
"""

import csv
import math
import random as _random
from pathlib import Path


# -- Klasa macierzy odległości --
class DistanceMatrix:
    """
    Symetryczna macierz odległości euklidesowych między nazwanymi miastami.

    Klucze to nazwy miast (ciągi znaków). Zapewnia wyszukiwanie O(1)
    i metody konwersji do formatu indeksowanego liczbowo,
    oczekiwanego przez moduł tsp_ga pracownika.
    """

    def __init__(self, matrix: dict):
        self._m = matrix
        self.cities: list[str] = list(matrix.keys())
        self.size: int = len(self.cities)

    def distance(self, a: str, b: str) -> float:
        """Zwróć odległość między miastem *a* i *b*."""
        return self._m[a][b]

    def to_serializable(self) -> dict:
        """Zwróć zagnieżdżony słownik nadający się do json.dumps."""
        return self._m

    def to_indexed(self) -> tuple[list[str], list[list[float]]]:
        """
        Konwertuj na ``(lista_nazw_miast, macierz_2D_float)`` indeksowaną liczbowo.

        Używane przez orkiestratora przy budowaniu ładunków zadań:
        moduł tsp_ga pracuje na indeksach liczbowych, nie nazwach miast.
        """
        cities = self.cities
        n = len(cities)
        mat = [[self._m[cities[i]][cities[j]] for j in range(n)] for i in range(n)]
        return cities, mat

    @classmethod
    def from_coordinates(
        cls, coords: dict[str, tuple[float, float]]
    ) -> "DistanceMatrix":
        """Zbuduj pełną symetryczną macierz z ``{miasto: (x, y)}`` współrzędnych."""
        cities = list(coords.keys())
        m: dict = {a: {} for a in cities}
        for a in cities:
            ax, ay = coords[a]
            for b in cities:
                if a == b:
                    m[a][b] = 0.0
                else:
                    bx, by = coords[b]
                    m[a][b] = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)
        return cls(m)

    @classmethod
    def from_dict(cls, matrix: dict) -> "DistanceMatrix":
        """Zbuduj z gotowego zagnieżdżonego słownika (np. wczytanego z JSON)."""
        return cls({a: dict(row) for a, row in matrix.items()})


# -- Generowanie losowych miast --
def generate_random_distance_matrix(n: int, seed: int = 42) -> DistanceMatrix:
    """
    Zbuduj ``DistanceMatrix`` dla *n* losowo rozmieszczonych miast 2D.

    Miasta są nazwane ``"0"`` … ``"n-1"``. Współrzędne losowane równomiernie
    z kwadratu [0, 1000] × [0, 1000].

    Parametry
    ----------
    n    : liczba miast (musi być >= 3)
    seed : seed generatora dla powtarzalności wyników
    """
    if n < 3:
        raise ValueError("n musi być >= 3 dla poprawnej instancji TSP")
    rng = _random.Random(seed)
    coords = {str(i): (rng.uniform(0, 1000), rng.uniform(0, 1000)) for i in range(n)}
    return DistanceMatrix.from_coordinates(coords)


# -- Pomocnik do sprawdzania liczb zmiennoprzecinkowych --
def _is_float(value: str) -> bool:
    """Zwróć True jeśli *value* można skonwertować na float."""
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


# -- Wczytywanie miast z CSV --
def load_distance_matrix_from_csv(path: str | Path) -> DistanceMatrix:
    """
    Zbuduj ``DistanceMatrix`` ze współrzędnych miast w pliku CSV.

    Obsługiwane formaty wierszy:
      1) ``nazwa,x,y``
      2) ``x,y``  (automatyczne nazwy: 0, 1, 2, ...)

    Wiersz nagłówkowy jest opcjonalny i automatycznie wykrywany.
    Puste wiersze i wiersze zaczynające się od ``#`` są ignorowane.
    Wymagane co najmniej 3 miasta.
    """
    coords_cell_start_idx = 2
    name_cell_idx = 1

    cor_idx = coords_cell_start_idx
    name_idx = name_cell_idx

    p = Path(path)
    coords: dict[str, tuple[float, float]] = {}

    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        auto_idx = 0
        for line_no, row in enumerate(reader, start=1):
            if not row:
                continue

            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            # Pomiń komentarze.
            if cells[0].startswith("#"):
                continue

            # Opcjonalna obsługa nagłówka — pomiń wiersz jeśli kolumny nie są liczbami.
            if line_no == 1:
                if len(cells) >= 3 and (
                    not _is_float(cells[cor_idx]) or not _is_float(cells[cor_idx + 1])
                ):
                    continue
                if len(cells) == 2 and (
                    not _is_float(cells[cor_idx]) or not _is_float(cells[cor_idx + 1])
                ):
                    continue

            if len(cells) >= 3:
                name = cells[name_idx]
                if not _is_float(cells[cor_idx]) or not _is_float(cells[cor_idx + 1]):
                    raise ValueError(
                        f"Nieprawidłowy wiersz CSV {line_no}: oczekiwano nazwa,x,y z liczbowymi x/y"
                    )
                x, y = float(cells[cor_idx]), float(cells[cor_idx + 1])
            elif len(cells) == 2:
                if not _is_float(cells[cor_idx]) or not _is_float(cells[cor_idx + 1]):
                    raise ValueError(
                        f"Nieprawidłowy wiersz CSV {line_no}: oczekiwano x,y z wartościami liczbowymi"
                    )
                name = str(auto_idx)
                auto_idx += 1
                x, y = float(cells[cor_idx]), float(cells[cor_idx + 1])
            else:
                raise ValueError(
                    f"Nieprawidłowy wiersz CSV {line_no}: oczekiwano 2 lub 3 kolumny"
                )

            if name in coords:
                raise ValueError(f"Zduplikowana nazwa miasta w CSV: {name!r}")
            coords[name] = (x, y)

    if len(coords) < 3:
        raise ValueError("CSV musi zawierać co najmniej 3 miasta")

    return DistanceMatrix.from_coordinates(coords)
