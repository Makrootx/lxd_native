"""
config_utils.py — Klasy i funkcje pomocnicze dla macierzy odległości TSP.

Zawartość:
  * DistanceMatrix                  — symetryczna macierz odległości euklidesowych
                                      między nazwanymi miastami
  * generate_random_distance_matrix — generowanie losowych miast
  * load_distance_matrix_from_csv   — wczytywanie miast z pliku CSV
  * load_distance_matrix_from_tsp   — wczytywanie instancji z pliku TSPLIB .tsp
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
    coords_cell_start_idx = 0
    name_cell_idx = 0

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


# ---------------------------------------------------------------------------
# Wczytywanie instancji TSPLIB (.tsp)
# ---------------------------------------------------------------------------


def _tsp_euc2d(ax: float, ay: float, bx: float, by: float) -> float:
    """Odległość euklidesowa zaokrąglona do najbliższej liczby całkowitej (TSPLIB EUC_2D)."""
    return float(round(math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)))


def _tsp_ceil_euc2d(ax: float, ay: float, bx: float, by: float) -> float:
    """Odległość euklidesowa sufitowa (TSPLIB CEIL_EUC_2D)."""
    return float(math.ceil(math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)))


def _tsp_att(ax: float, ay: float, bx: float, by: float) -> float:
    """Pseudo-euklidesowa odległość ATT (TSPLIB ATT, np. att48, att532)."""
    rij = math.sqrt(((ax - bx) ** 2 + (ay - by) ** 2) / 10.0)
    tij = round(rij)
    return float(tij + 1 if tij < rij else tij)


def _tsp_geo(ax: float, ay: float, bx: float, by: float) -> float:
    """
    Geograficzna odległość (TSPLIB GEO) w kilometrach.

    Wejście: ax/ay to stopnie dziesiętne szerokości/długości geograficznej.
    """
    _PI = math.pi
    _RRR = 6378.388

    def _to_rad(deg_dec: float) -> float:
        deg = int(deg_dec)
        minutes = deg_dec - deg
        return _PI * (deg + 5.0 * minutes / 3.0) / 180.0

    lat_i, lon_i = _to_rad(ax), _to_rad(ay)
    lat_j, lon_j = _to_rad(bx), _to_rad(by)
    q1 = math.cos(lon_i - lon_j)
    q2 = math.cos(lat_i - lat_j)
    q3 = math.cos(lat_i + lat_j)
    return float(int(_RRR * math.acos(0.5 * ((1.0 + q1) * q2 - (1.0 - q1) * q3)) + 1.0))


def _tsp_man2d(ax: float, ay: float, bx: float, by: float) -> float:
    """Odległość Manhattan (TSPLIB MAN_2D)."""
    return float(round(abs(ax - bx) + abs(ay - by)))


def _tsp_max2d(ax: float, ay: float, bx: float, by: float) -> float:
    """Odległość Czebyszewa (TSPLIB MAX_2D)."""
    return float(round(max(abs(ax - bx), abs(ay - by))))


_COORD_DIST_FN = {
    "EUC_2D": _tsp_euc2d,
    "CEIL_EUC_2D": _tsp_ceil_euc2d,
    "ATT": _tsp_att,
    "GEO": _tsp_geo,
    "MAN_2D": _tsp_man2d,
    "MAX_2D": _tsp_max2d,
}


def load_distance_matrix_from_tsp(path: str | Path) -> DistanceMatrix:
    """
    Zbuduj ``DistanceMatrix`` z pliku TSPLIB w formacie ``.tsp``.

    Obsługiwane typy wag krawędzi (EDGE_WEIGHT_TYPE):
      - ``EUC_2D``      — euklidesowa 2D, zaokrąglona
      - ``CEIL_EUC_2D`` — euklidesowa 2D, sufitowa
      - ``ATT``         — pseudo-euklidesowa (att48, att532)
      - ``GEO``         — geograficzna (wielki okrąg)
      - ``MAN_2D``      — Manhattan
      - ``MAX_2D``      — Czebyszew
      - ``EXPLICIT``    — jawna macierz (FULL_MATRIX, UPPER_ROW, LOWER_ROW,
                          UPPER_DIAG_ROW, LOWER_DIAG_ROW)

    Sekcje danych:
      - ``NODE_COORD_SECTION`` — współrzędne wierzchołków (dla typów koordynatowych)
      - ``EDGE_WEIGHT_SECTION`` — surowe wartości wag (dla ``EXPLICIT``)

    Parametry
    ----------
    path : ścieżka do pliku .tsp

    Zwraca
    -------
    DistanceMatrix
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    # ---- parsowanie nagłówka ----
    headers: dict[str, str] = {}
    data_section: str | None = None
    data_lines: list[str] = []

    _KNOWN_SECTIONS = {
        "NODE_COORD_SECTION",
        "EDGE_WEIGHT_SECTION",
        "DISPLAY_DATA_SECTION",
        "TOUR_SECTION",
        "EOF",
    }

    for raw in lines:
        line = raw.strip()
        if not line or line == "EOF":
            break

        # Sekcja danych zaczyna się gdy napotkamy jej nagłówek
        if line in _KNOWN_SECTIONS:
            data_section = line
            continue

        if data_section is not None:
            data_lines.append(line)
            continue

        # Klucz : wartość lub klucz = wartość
        if ":" in line:
            key, _, val = line.partition(":")
        elif "=" in line:
            key, _, val = line.partition("=")
        else:
            # Może to już początek sekcji bez jawnego słowa kluczowego — ignoruj
            continue
        headers[key.strip().upper()] = val.strip()

    weight_type = headers.get("EDGE_WEIGHT_TYPE", "EUC_2D").upper()
    weight_format = headers.get("EDGE_WEIGHT_FORMAT", "FULL_MATRIX").upper()
    dimension_str = headers.get("DIMENSION", "")
    if not dimension_str:
        raise ValueError(f"Brakujący nagłówek DIMENSION w pliku {path}")
    n = int(dimension_str)

    # ---- NODE_COORD_SECTION — typy koordynatowe ----
    if weight_type in _COORD_DIST_FN:
        dist_fn = _COORD_DIST_FN[weight_type]
        coords: dict[str, tuple[float, float]] = {}

        # Jeśli sekcja danych nie została jawnie zidentyfikowana w pętli,
        # spróbuj znaleźć ją ponownie (niektóre pliki mają dane przed EOF)
        if data_section != "NODE_COORD_SECTION":
            data_lines = []
            in_section = False
            for raw in lines:
                line = raw.strip()
                if line == "NODE_COORD_SECTION":
                    in_section = True
                    continue
                if in_section:
                    if line in _KNOWN_SECTIONS or line == "EOF":
                        break
                    data_lines.append(line)

        for raw in data_lines:
            parts = raw.split()
            if len(parts) < 3:
                continue
            city_id = str(int(parts[0]))  # normalizuj: 0001 → '1', 1 → '1'
            x, y = float(parts[1]), float(parts[2])
            coords[city_id] = (x, y)

        if len(coords) != n:
            raise ValueError(
                f"Oczekiwano {n} miast (DIMENSION), wczytano {len(coords)} z NODE_COORD_SECTION"
            )

        city_ids = list(
            coords.keys()
        )  # zachowaj kolejność z pliku (mogą być np. 0001, 0002...)
        m: dict = {a: {} for a in city_ids}
        for i, a in enumerate(city_ids):
            ax, ay = coords[a]
            for j, b in enumerate(city_ids):
                if i == j:
                    m[a][b] = 0.0
                else:
                    bx, by = coords[b]
                    m[a][b] = dist_fn(ax, ay, bx, by)
        return DistanceMatrix(m)

    # ---- EDGE_WEIGHT_SECTION — typ EXPLICIT ----
    if weight_type == "EXPLICIT":
        # Zbierz wszystkie tokeny liczbowe z sekcji wag
        if data_section != "EDGE_WEIGHT_SECTION":
            data_lines = []
            in_section = False
            for raw in lines:
                line = raw.strip()
                if line == "EDGE_WEIGHT_SECTION":
                    in_section = True
                    continue
                if in_section:
                    if line in _KNOWN_SECTIONS or line == "EOF":
                        break
                    data_lines.append(line)

        tokens: list[float] = []
        for raw in data_lines:
            for tok in raw.split():
                try:
                    tokens.append(float(tok))
                except ValueError:
                    pass

        city_ids = [str(i + 1) for i in range(n)]
        m = {a: {b: 0.0 for b in city_ids} for a in city_ids}

        if weight_format == "FULL_MATRIX":
            if len(tokens) < n * n:
                raise ValueError(
                    "Za mało wartości w EDGE_WEIGHT_SECTION dla FULL_MATRIX"
                )
            for i in range(n):
                for j in range(n):
                    m[city_ids[i]][city_ids[j]] = tokens[i * n + j]

        elif weight_format in {"UPPER_ROW", "UPPER_DIAG_ROW"}:
            diag = weight_format == "UPPER_DIAG_ROW"
            idx = 0
            for i in range(n):
                start = i if diag else i + 1
                for j in range(start, n):
                    v = tokens[idx]
                    idx += 1
                    m[city_ids[i]][city_ids[j]] = v
                    m[city_ids[j]][city_ids[i]] = v

        elif weight_format in {"LOWER_ROW", "LOWER_DIAG_ROW"}:
            diag = weight_format == "LOWER_DIAG_ROW"
            idx = 0
            for i in range(n):
                end = i + 1 if diag else i
                for j in range(0, end):
                    v = tokens[idx]
                    idx += 1
                    m[city_ids[i]][city_ids[j]] = v
                    m[city_ids[j]][city_ids[i]] = v

        else:
            raise ValueError(f"Nieobsługiwany EDGE_WEIGHT_FORMAT: {weight_format}")

        return DistanceMatrix(m)

    raise ValueError(
        f"Nieobsługiwany EDGE_WEIGHT_TYPE: {weight_type!r}. "
        f"Obsługiwane: {', '.join(sorted(_COORD_DIST_FN) + ['EXPLICIT'])}"
    )
