"""
cli.py — Interfejs wiersza poleceń rozproszonego orkiestratora TSP (pylxd v2).

Grupy argumentów odpowiadają implementacji referencyjnej pw-lxd
(problem, GA, migracja, raportowanie, metadane) z dodatkową grupą
*cluster* dla ustawień specyficznych dla LXD.

Pierwszeństwo konfiguracji (od najniższego do najwyższego):
  1. Wartości domyślne wbudowane (GAConfigModel / config.py)
  2. Plik konfiguracyjny JSON (--config)
  3. Jawne flagi CLI (zawsze nadpisują)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config.config import (
    DEFAULT_CITIES,
    DEFAULT_CITIES_SEED,
    DEFAULT_CLEANUP,
    DEFAULT_WORKERS,
    DISTANCE_MATRIX,
    LXD_CONCURRENCY,
)

from utils.config_utils import (
    generate_random_distance_matrix,
    load_distance_matrix_from_csv,
)

from config.ga_config_model import GAConfigModel
from orchestrator import GATSPOrchestrator

# -- Mapowanie flag CLI na nazwy dest argparse --
# Używane do wykrywania flag podanych jawnie przez użytkownika,
# co pozwala poprawnie implementować pierwszeństwo: domyślne < plik < CLI.
_FLAG_TO_DEST = {
    "--config": "config",
    "--cities": "cities",
    "--cities-csv": "cities_csv",
    "--cities-seed": "cities_seed",
    "--workers": "workers",
    "--concurrency": "concurrency",
    "--population": "population",
    "--generations": "generations",
    "--mutation": "mutation",
    "--elite": "elite",
    "--tournament": "tournament",
    "--two-opt-attempts": "two_opt_attempts",
    "--seed": "seed",
    "--migration-strategy": "migration_strategy",
    "--migration-interval": "migration_interval",
    "--immigrants": "immigrants",
    "--output": "output",
    "--report-interval": "report_interval",
    "--debug-routes": "debug_routes",
    "--cleanup": "cleanup",
    "--metadata-run-id": "metadata_run_id",
    "--metadata-scenario-name": "metadata_scenario_name",
    "--metadata-containers-per-node": "metadata_containers_per_node",
    "--metadata-cpu-limit": "metadata_cpu_limit",
    "--metadata-code-version": "metadata_code_version",
}


# -- Wykrywanie jawnych flag CLI --
def _explicit_cli_dests(argv: list[str]) -> set[str]:
    """Zwróć zestaw nazw dest argparse podanych jawnie w argv."""
    explicit: set[str] = set()
    for token in argv:
        if not token.startswith("--"):
            continue
        flag = token.split("=", 1)[0]
        dest = _FLAG_TO_DEST.get(flag)
        if dest:
            explicit.add(dest)
    return explicit


# -- Ładowanie pliku konfiguracyjnego --
def _load_config_file(path: str | None) -> dict:
    """
    Załaduj konfigurację orkiestratora z pliku JSON.

    Plik może być niepełny — nieznane klucze są ignorowane.
    Akceptuje zarówno klucze snake_case jak i kebab-case.
    """
    if not path:
        return {}
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Plik --config nie znaleziony: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"--config musi być poprawnym JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError("Korzeń JSON --config musi być obiektem")
    # Normalizuj klucze: zamień myślniki na podkreślenia.
    return {str(k).replace("-", "_"): v for k, v in data.items()}


# -- Stosowanie nadpisań z pliku konfiguracyjnego --
def _apply_config_overrides(
    args: argparse.Namespace,
    config_data: dict,
    explicit_cli: set[str],
) -> argparse.Namespace:
    """
    Zastosuj wartości z pliku konfiguracyjnego dla parametrów niepodanych w CLI.

    Pierwszeństwo: wartości domyślne < plik konfiguracyjny < jawne flagi CLI.
    """
    allowed = {
        "cities",
        "cities_seed",
        "workers",
        "concurrency",
        "cities_csv",
        "population",
        "generations",
        "mutation",
        "elite",
        "tournament",
        "two_opt_attempts",
        "seed",
        "migration_strategy",
        "migration_interval",
        "immigrants",
        "output",
        "report_interval",
        "debug_routes",
        "cleanup",
        "metadata_run_id",
        "metadata_scenario_name",
        "metadata_containers_per_node",
        "metadata_cpu_limit",
        "metadata_code_version",
    }
    for key, value in config_data.items():
        if key not in allowed:
            continue
        # Pomiń jeśli użytkownik podał tę flagę jawnie w CLI.
        if key in explicit_cli:
            continue
        setattr(args, key, value)
    return args


# -- Parsowanie argumentów --
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=("Rozproszony wyspowy GA dla TSP działający na kontenerach LXD."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=(
            "Ścieżka do pliku JSON z parametrami orkiestratora. "
            "Plik może być niepełny. Flagi CLI zawsze nadpisują wartości z pliku."
        ),
    )

    # -- Definicja problemu TSP --
    problem = parser.add_argument_group("Problem TSP")
    problem.add_argument(
        "--cities",
        type=int,
        default=DEFAULT_CITIES,
        help=(
            "Liczba losowych miast 2D do wygenerowania. "
            "0 (domyślnie) = użyj wbudowanej mapy 100 nazwanych miast. "
            "Musi być >= 3 gdy ustawione."
        ),
    )
    problem.add_argument(
        "--cities-csv",
        type=str,
        default=None,
        dest="cities_csv",
        help=(
            "Ścieżka do pliku CSV ze współrzędnymi miast. "
            "Obsługiwane wiersze: nazwa,x,y lub x,y. "
            "Gdy podane, ma pierwszeństwo przed --cities."
        ),
    )
    problem.add_argument(
        "--cities-seed",
        type=int,
        default=DEFAULT_CITIES_SEED,
        dest="cities_seed",
        help="Seed losowy używany przy generowaniu losowej mapy miast (--cities > 0).",
    )

    # -- Klaster LXD --
    cluster = parser.add_argument_group("Klaster LXD")
    cluster.add_argument(
        "--workers",
        type=str,
        default=str(DEFAULT_WORKERS),
        help=(
            "Lista nazw kontenerów LXD oddzielona przecinkami, np. worker-1,worker-2. "
            "Alternatywnie podaj liczbę całkowitą N żeby użyć worker-1…worker-N. "
            f"Domyślnie worker-1..worker-{DEFAULT_WORKERS}."
        ),
    )
    cluster.add_argument(
        "--concurrency",
        type=int,
        default=LXD_CONCURRENCY,
        help="Maksymalna liczba kontenerów prowizjonowanych / wykonywanych równolegle.",
    )

    # -- Algorytm genetyczny --
    ga = parser.add_argument_group("Algorytm genetyczny")
    ga_defaults = GAConfigModel()
    ga.add_argument(
        "--population",
        type=int,
        default=ga_defaults.population_size,
        help="Rozmiar populacji na wyspę (kontener).",
    )
    ga.add_argument(
        "--generations",
        type=int,
        default=ga_defaults.generations,
        help="Liczba generacji GA do uruchomienia na każdej wyspie.",
    )
    ga.add_argument(
        "--mutation",
        type=float,
        default=ga_defaults.mutation,
        help="Prawdopodobieństwo mutacji swap [0.0, 1.0].",
    )
    ga.add_argument(
        "--elite",
        type=int,
        default=ga_defaults.elite,
        help="Liczba elit kopiowanych bez zmian do następnej generacji.",
    )
    ga.add_argument(
        "--tournament",
        type=int,
        default=ga_defaults.tournament,
        help="Rozmiar turnieju selekcji.",
    )
    ga.add_argument(
        "--two-opt-attempts",
        type=int,
        default=ga_defaults.two_opt_attempts,
        dest="two_opt_attempts",
        help="Liczba losowych prób poprawy 2-opt na potomka.",
    )
    ga.add_argument(
        "--seed",
        type=int,
        default=ga_defaults.seed,
        help="Bazowy seed losowy wysyłany do każdej wyspy.",
    )

    # -- Migracja --
    migration = parser.add_argument_group("Migracja")
    migration.add_argument(
        "--migration-strategy",
        choices=["none", "ring", "global-best"],
        default=ga_defaults.migration_strategy,
        dest="migration_strategy",
        help=(
            "Strategia migracji między wyspami. "
            "'none' = niezależne jednorazowe wykonanie (domyślnie). "
            "'ring' = każda wyspa otrzymuje elity od lewego sąsiada "
            "co migration_interval generacji. "
            "'global-best' = każda wyspa otrzymuje globalnie najlepsze trasy. "
            "Obie strategie używają wielorundowego wykonania sterowanego przez orkiestratora."
        ),
    )
    migration.add_argument(
        "--migration-interval",
        type=int,
        default=ga_defaults.migration_interval,
        dest="migration_interval",
        help="Migruj co N generacji.",
    )
    migration.add_argument(
        "--immigrants",
        type=int,
        default=ga_defaults.immigrants,
        help="Liczba najlepszych osobników migrujących w każdym interwale.",
    )

    # -- Raportowanie --
    reporting = parser.add_argument_group("Raportowanie")
    reporting.add_argument(
        "--output",
        type=str,
        default=None,
        help=(
            "Ścieżka pliku JSON z wynikami zapisywanego przez orkiestratora "
            "po zakończeniu wszystkich wysp. Pominięcie = tylko stdout."
        ),
    )
    reporting.add_argument(
        "--report-interval",
        type=int,
        default=ga_defaults.report_interval,
        dest="report_interval",
        help="Zapisuj punkt historii generacji co N generacji.",
    )
    reporting.add_argument(
        "--debug-routes",
        action="store_true",
        default=ga_defaults.debug_routes,
        dest="debug_routes",
        help="Włącz walidację O(n) permutacji tras TSP podczas ewolucji.",
    )
    reporting.add_argument(
        "--cleanup",
        action="store_true",
        default=DEFAULT_CLEANUP,
        help=(
            "Zatrzymaj i usuń wszystkie kontenery pracowników po zakończeniu. "
            "Przydatne dla jednorazowych eksperymentów."
        ),
    )

    # -- Metadane --
    meta = parser.add_argument_group("Metadane (zapisywane w wynikowym JSON)")
    meta.add_argument(
        "--metadata-run-id",
        type=str,
        default="manual-run",
        dest="metadata_run_id",
        help="Czytelny identyfikator uruchomienia eksperymentu.",
    )
    meta.add_argument(
        "--metadata-scenario-name",
        type=str,
        default="default",
        dest="metadata_scenario_name",
        help="Czytelna nazwa scenariusza.",
    )
    meta.add_argument(
        "--metadata-containers-per-node",
        type=int,
        default=None,
        dest="metadata_containers_per_node",
        help="Liczba kontenerów LXD na fizyczny węzeł klastra.",
    )
    meta.add_argument(
        "--metadata-cpu-limit",
        type=str,
        default=None,
        dest="metadata_cpu_limit",
        help="Limit CPU LXD stosowany do każdego kontenera (np. '1', '0.5').",
    )
    meta.add_argument(
        "--metadata-code-version",
        type=str,
        default=None,
        dest="metadata_code_version",
        help="Etykieta wersji kodu, hash commita git lub tag.",
    )

    return parser.parse_args()


# -- Walidacja argumentów --
def validate_args(args: argparse.Namespace) -> None:
    """Sprawdź podstawowe warunki wstępne argumentów CLI."""
    if args.concurrency < 1:
        raise ValueError("--concurrency musi być >= 1")
    if args.cities < 0:
        raise ValueError("--cities musi być >= 0")
    if args.cities != 0 and args.cities < 3:
        raise ValueError("--cities musi być >= 3 gdy ustawione")


# -- Rozwiązywanie listy pracowników --
def resolve_workers(workers_arg: str | int | list | None) -> list[str]:
    """
    Przetwórz argument ``--workers`` na listę nazw kontenerów.

    Akceptuje:
    * ``None``                 → domyślna liczba pracowników z konfiguracji
    * ``"3"``                  → ``["worker-1", "worker-2", "worker-3"]``
    * ``"worker-1,worker-2"``  → ``["worker-1", "worker-2"]``
    * lista stringów           → zwrócona bezpośrednio
    """
    if isinstance(workers_arg, list):
        names = [str(w).strip() for w in workers_arg if str(w).strip()]
        if not names:
            raise ValueError("--workers dało pustą listę")
        return names
    if isinstance(workers_arg, int):
        if workers_arg < 1:
            raise ValueError("Liczba --workers musi być >= 1")
        return [f"worker-{i}" for i in range(1, workers_arg + 1)]
    if workers_arg is None:
        return [f"worker-{i}" for i in range(1, DEFAULT_WORKERS + 1)]
    if workers_arg.isdigit():
        n = int(workers_arg)
        if n < 1:
            raise ValueError("Liczba --workers musi być >= 1")
        return [f"worker-{i}" for i in range(1, n + 1)]
    names = [w.strip() for w in workers_arg.split(",") if w.strip()]
    if not names:
        raise ValueError("--workers dało pustą listę")
    return names


# -- Główny punkt wejścia --
def main() -> None:
    """Parsuj argumenty, zbuduj konfigurację i uruchom orkiestratora TSP."""
    # Zbierz jawne flagi CLI przed parsowaniem (by obsłużyć pierwszeństwo).
    explicit_cli = _explicit_cli_dests(sys.argv[1:])
    args = parse_args()
    file_cfg = _load_config_file(args.config)
    args = _apply_config_overrides(args, file_cfg, explicit_cli)
    validate_args(args)
    workers = resolve_workers(args.workers)

    # -- Wybór macierzy odległości --
    if args.cities_csv:
        # Plik CSV ma najwyższy priorytet.
        matrix = load_distance_matrix_from_csv(args.cities_csv)
    elif args.cities > 0:
        # Losowe miasta z podanym seedem.
        matrix = generate_random_distance_matrix(args.cities, args.cities_seed)
    else:
        # Wbudowana mapa 100 nazwanych miast.
        matrix = DISTANCE_MATRIX

    # -- Budowanie modelu GA --
    ga_config = GAConfigModel(
        population_size=args.population,
        generations=args.generations,
        mutation=args.mutation,
        elite=args.elite,
        tournament=args.tournament,
        two_opt_attempts=args.two_opt_attempts,
        seed=args.seed,
        migration_strategy=args.migration_strategy,
        migration_interval=args.migration_interval,
        immigrants=args.immigrants,
        report_interval=args.report_interval,
        debug_routes=args.debug_routes,
    )

    # -- Metadane do dokumentu wynikowego --
    metadata = {
        "run_id": args.metadata_run_id,
        "scenario_name": args.metadata_scenario_name,
        "containers_per_node": args.metadata_containers_per_node,
        "cpu_limit": args.metadata_cpu_limit,
        "code_version": args.metadata_code_version,
        "worker_count": len(workers),
    }

    # -- Uruchomienie orkiestratora --
    GATSPOrchestrator(
        distance_matrix=matrix,
        workers=workers,
        concurrency=args.concurrency,
        ga_config=ga_config,
        output=args.output,
        metadata=metadata,
        cleanup=args.cleanup,
    ).run()
