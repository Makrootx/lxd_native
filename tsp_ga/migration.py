"""
migration.py — Strategie migracji sterowane przez orkiestratora.

Funkcje wywoływane przez GATSPOrchestrator pomiędzy rundami wykonania wysp.

Każdy słownik wynikowy pracownika powinien zawierać:
  "elite_routes"    : list[list[int]]  — top-k tras wg dystansu
  "elite_distances" : list[float]      — odpowiadające dystanse (ta sama kolejność)
"""

from __future__ import annotations


# -- Migracja pierścieniowa --
def orchestrator_ring_migration(
    worker_results: dict,
    workers: list,
    immigrants_count: int,
) -> dict:
    """
    Topologia pierścieniowa: worker[i] otrzymuje najlepsze trasy z worker[(i-1) % n].

    Zwraca {nazwa_pracownika: list[trasa]} — imigrantów do wstrzyknięcia
    w zadaniu następnej rundy każdego pracownika.
    """
    n = len(workers)
    result: dict = {}
    for i, worker in enumerate(workers):
        # Źródłem imigrantów jest pracownik po lewej stronie pierścienia.
        source = workers[(i - 1 + n) % n]
        elite = worker_results.get(source, {}).get("elite_routes", [])
        result[worker] = elite[:immigrants_count]
    return result


# -- Migracja globalnie najlepszych --
def orchestrator_global_best_migration(
    worker_results: dict,
    workers: list,
    immigrants_count: int,
) -> dict:
    """
    Topologia globalnie najlepszych: każdy pracownik otrzymuje elity
    z puli wszystkich wysp łącznie.

    Zwraca {nazwa_pracownika: list[trasa]} — ta sama lista imigrantów
    dla każdego pracownika.
    """
    # Zbierz elity ze wszystkich wysp z ich dystansami.
    all_elites: list[tuple[float, list]] = []
    for res in worker_results.values():
        routes = res.get("elite_routes", [])
        dists = res.get("elite_distances", [])
        for j, route in enumerate(routes):
            dist = dists[j] if j < len(dists) else float("inf")
            all_elites.append((dist, route))

    # Sortuj globalnie i weź top-(immigrants_count * liczba_wysp) tras.
    all_elites.sort(key=lambda x: x[0])
    global_immigrants = [r for _, r in all_elites[: immigrants_count * len(workers)]]
    return {w: global_immigrants for w in workers}


# -- Dyspozytor migracji --
def orchestrator_migrate(
    strategy: str,
    worker_results: dict,
    workers: list,
    immigrants_count: int,
) -> dict:
    """
    Wywołaj odpowiednią funkcję migracji orkiestratora.

    Parametry
    ---------
    strategy         : "none" | "ring" | "global-best"
    worker_results   : {nazwa_pracownika: słownik_wynikowy} z ostatniej rundy
    workers          : uporządkowana lista nazw pracowników (kolejność ważna dla ring)
    immigrants_count : liczba elit do przesłania do każdego pracownika

    Zwraca
    ------
    {nazwa_pracownika: list[trasa]} — imigranci do wstrzyknięcia w następnej rundzie.
    Puste listy gdy strategia to "none" lub jest za mało wysp.
    """
    if strategy == "none" or immigrants_count <= 0 or len(workers) <= 1:
        return {w: [] for w in workers}
    if strategy == "ring":
        return orchestrator_ring_migration(worker_results, workers, immigrants_count)
    if strategy == "global-best":
        return orchestrator_global_best_migration(
            worker_results, workers, immigrants_count
        )
    raise ValueError(f"Nieobsługiwana strategia migracji: {strategy!r}")
