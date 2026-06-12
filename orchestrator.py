"""
orchestrator.py — Rozproszony orkiestrator TSP oparty na wyspowym GA.

Wielorundowa migracja
---------------------
Gdy --migration-strategy to 'ring' lub 'global-best', orkiestrator w pewny sposob
modyfikuje zadania GA wysyłane do pracowników, wstrzykując imigrantów i poprzednią
populację między rundami. Orkiestrator sam steruje migracją przez rundy
po migration_interval generacji każda:

  Runda 1:  wszystkie wyspy startują z losową populacją, ewoluują migration_interval gen
  Runda 2:  orkiestrator stosuje topologię migracji, wyspy kontynuują ze swoją
            populacją końcową i wstrzykniętymi imigrantami
  ...
  Runda N:  ostatni fragment generacji, zbieranie wyników końcowych

Używa pylxd file API + ThreadPoolExecutor do dystrybucji zadań i zbierania wyników.
"""

import json
import itertools
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config.ga_config_model import GAConfigModel
from lxd_manager import LXDOrchestrator
from tsp_ga.migration import orchestrator_migrate


# -- Klasa orkiestratora --
class GATSPOrchestrator:
    """
    Dystrybuuje instancję TSP między kontenery LXD pracowników używając
    wyspowego algorytmu genetycznego z migracją sterowaną przez orkiestratora.
    """

    def __init__(
        self,
        distance_matrix=None,
        workers: list = None,
        concurrency: int = None,
        ga_config: GAConfigModel | None = None,
        output: str = None,
        metadata: dict = None,
        cleanup: bool = False,
    ):
        self.matrix = distance_matrix
        self.workers = workers
        self.concurrency = concurrency
        self.lxd = LXDOrchestrator(concurrency=self.concurrency)
        self.output = output
        self.metadata = metadata or {}
        self.cleanup = cleanup

        self.ga_config = ga_config if ga_config is not None else GAConfigModel()

    # -- Budowanie zadania --
    def _build_base_task(self) -> dict:
        """Buduje słownik zadania bazowego wysyłanego do każdego pracownika w każdej rundzie."""
        city_names, dist_matrix = self.matrix.to_indexed()
        return {
            "city_names": city_names,
            "distance_matrix": dist_matrix,
            **self.ga_config.worker_task_dict(),
        }

    def _write_task(self, task: dict, path: str = "task.json") -> None:
        """Zapisuje słownik zadania do pliku JSON (metoda używana przy testach)."""
        base = Path(__file__).parent
        with open(base / path, "w") as fh:
            json.dump(task, fh)

    # -- Dystrybucja kodu --
    def _distribute_common(self) -> None:
        """Przesyła pliki pakietu workera do każdego kontenera."""
        print("[Master] Przesyłanie pakietu kontenera (worker.py + tsp_ga/)...")
        base = Path(__file__).parent
        container_dir = base / "container"
        self.lxd.push_files(
            self.workers,
            [
                (str(container_dir / "worker.py"), "/root/worker.py"),
            ],
        )
        self.lxd.push_directory_to_all(
            self.workers,
            local_dir=str(container_dir / "tsp_ga"),
            remote_dir="/root/tsp_ga",
        )

    def _push_worker_tasks(self, worker_tasks: dict) -> None:
        """Wysyła różny payload task.json do każdego pracownika równolegle."""

        def _push(worker: str) -> None:
            data = json.dumps(worker_tasks[worker]).encode("utf-8")
            self.lxd._shared.push_bytes(worker, "/root/task.json", data)

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            list(pool.map(_push, self.workers))

    # -- Surowe wykonanie --
    def _execute_raw(self) -> dict:
        """
        Uruchamia wszystkich pracowników i zbiera wyniki JSON.
        Zwraca ``{nazwa_pracownika: słownik_wynikowy}``.
        """
        results: dict = {}
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = {
                pool.submit(self.lxd.run_worker_script, w): w for w in self.workers
            }
            for future in as_completed(futures):
                worker, stdout, stderr = future.result()
                if stdout:
                    try:
                        results[worker] = json.loads(stdout.strip())
                    except json.JSONDecodeError:
                        print(f"  -> {worker}: błąd dekodowania JSON — {stdout[:120]}")
                else:
                    print(f"  -> {worker} błąd: {stderr.strip()[:200]}")
        return results

    # -- Wykonanie jednorazowe (migration_strategy = "none") --
    def _execute_single(self) -> list[dict]:
        """
        Wykonanie jednorazowe: każda wyspa dostaje odrębny seed.

        Seed każdej wyspy jest unikalny, co zapewnia niezależną
        ewolucję na każdej wyspie przy braku migracji.
        """
        base_seed = self.ga_config.seed
        worker_tasks = {}
        t0 = time.time()
        base_task = self._build_base_task()
        for w_idx, worker in enumerate(self.workers):
            task = base_task.copy()
            # Odrębny seed per wyspa: base + indeks * 997 (liczba pierwsza).
            task["seed"] = base_seed + w_idx * 997
            worker_tasks[worker] = task
        self._push_worker_tasks(worker_tasks)
        t1 = time.time()
        print(f"  -> Czas wysyłania: {t1 - t0:.1f}s")
        raw = self._execute_raw()
        for worker, res in raw.items():
            print(
                f"  -> {worker}: dystans={res['distance']:.4f}  "
                f"czas={res.get('elapsed_seconds', 0):.1f}s"
            )
        return list(raw.values())

    # -- Wykonanie wielorundowe (ring / global-best) --
    def _execute_rounds(self) -> list[dict]:
        """
        Wielorundowa pętla wykonania z migracją sterowaną przez orkiestratora.

        Każda runda trwa migration_interval generacji. Po każdej rundzie
        (poza ostatnią) orkiestrator:
          1. Zbiera elite_routes z każdej wyspy.
          2. Stosuje topologię migracji (pierścień lub globalnie najlepsze).
          3. Wstrzykuje imigrantów i poprzednią final_population do zadania
             następnej rundy każdego pracownika.


        Seedy pracowników są zróżnicowane: base + runda*100_003 + indeks*997.
        Dwa współmierne przesunięcia gwarantują szeroki rozstęp seedów,
        co sprawia że wyspy ewoluują niezależnie przez całe uruchomienie.
        """
        strategy = self.ga_config.migration_strategy
        migration_interval = self.ga_config.migration_interval
        total_generations = self.ga_config.generations
        immigrants_count = self.ga_config.immigrants
        base_seed = self.ga_config.seed

        # Stan trwały każdej wyspy między rundami.
        populations: dict = {w: None for w in self.workers}  # list[Route] lub None
        immigrants: dict = {w: [] for w in self.workers}  # trasy imigrantów

        # Akumulowane wyniki między rundami.
        best_results: dict = {w: None for w in self.workers}
        full_history: dict = {w: [] for w in self.workers}
        total_migration: dict = {w: 0 for w in self.workers}

        rounds_done = 0
        gens_remaining = total_generations

        while gens_remaining > 0:
            round_gens = min(migration_interval, gens_remaining)
            is_last = gens_remaining <= migration_interval

            print(
                f"  [runda {rounds_done + 1}] "
                f"{round_gens} gen"
                + (
                    f"  wstrzykiwanie imigrantów ({strategy})"
                    if rounds_done > 0
                    else ""
                )
            )

            # Buduje per-pracownik zadanie dla tej rundy.
            worker_tasks: dict = {}
            base_task = self._build_base_task()
            for w_idx, worker in enumerate(self.workers):
                task = base_task.copy()
                # Seed zróżnicowany: base + runda*100_003 + indeks_wyspy*997.
                worker_seed = base_seed + rounds_done * 100_003 + w_idx * 997
                task["generations"] = round_gens
                task["seed"] = worker_seed
                if populations[worker] is not None:
                    task["initial_population"] = populations[worker]
                if immigrants[worker]:
                    task["immigrant_routes"] = immigrants[worker]
                worker_tasks[worker] = task

            self._push_worker_tasks(worker_tasks)
            round_results = self._execute_raw()

            # Aktualizuje stan wyspy i wyświetla postęp.
            for worker in self.workers:
                res = round_results.get(worker)
                if res is None:
                    continue
                populations[worker] = res.get("final_population")
                full_history[worker].extend(res.get("history", []))

                if immigrants[worker]:
                    total_migration[worker] += 1

                prev_best = best_results[worker]
                if prev_best is None or res["distance"] < prev_best["distance"]:
                    best_results[worker] = res

                print(
                    f"    {worker}: dystans={res['distance']:.4f}  "
                    f"czas={res.get('elapsed_seconds', 0):.1f}s"
                )

            # Oblicza imigrantów na następną rundę.
            if not is_last and immigrants_count > 0:
                immigrants = orchestrator_migrate(
                    strategy=strategy,
                    worker_results=round_results,
                    workers=self.workers,
                    immigrants_count=immigrants_count,
                )
                receiving = sum(1 for v in immigrants.values() if v)
                print(
                    f"  [migracja/{strategy}] "
                    f"{receiving}/{len(self.workers)} pracowników otrzymuje imigrantów"
                )

            rounds_done += 1
            gens_remaining -= round_gens

        # Scala akumulowaną historię z najlepszym wynikiem każdej wyspy.
        final: list[dict] = []
        for worker in self.workers:
            res = best_results.get(worker)
            if res is None:
                continue
            res = dict(res)
            res["history"] = full_history[worker]
            res["migration_count"] = total_migration[worker]
            final.append(res)

        return final

    # -- Metryki różnorodności (diversity) --
    @staticmethod
    def _route_edges(route: list) -> frozenset:
        """Zwraca frozenset krawędzi trasy (nieukierunkowane pary miast)."""
        n = len(route)
        edges = set()
        for i in range(n):
            a, b = route[i], route[(i + 1) % n]
            edges.add((a, b) if a < b else (b, a))
        return frozenset(edges)

    def _edge_distance(self, ra: list, rb: list) -> float:
        """Oblicza odległość krawędziową dwóch tras: 1 - |wspólne krawędzie| / |wszystkie krawędzie|."""
        ea, eb = self._route_edges(ra), self._route_edges(rb)
        if not ea and not eb:
            return 0.0
        return 1.0 - len(ea & eb) / max(len(ea), len(eb))

    def _diversity(self, results: list[dict]) -> dict:
        """
        Oblicza metryki różnorodności tras między wyspami.

        Używa odległości krawędziowej parami: dwie trasy z identycznym
        zbiorem krawędzi mają dystans 0.0; całkowicie różne trasy — 1.0.
        """
        routes = [r["path"] for r in results]
        unique = len({tuple(r) for r in routes})
        pairs = [
            self._edge_distance(a, b) for a, b in itertools.combinations(routes, 2)
        ]
        return {
            "unique_best_routes": unique,
            "pairwise_comparisons": len(pairs),
            "mean_pairwise_edge_distance": statistics.mean(pairs) if pairs else 0.0,
            "min_pairwise_edge_distance": min(pairs) if pairs else 0.0,
            "max_pairwise_edge_distance": max(pairs) if pairs else 0.0,
        }

    # -- Raportowanie wyników --
    def _build_result_document(
        self, results: list[dict], elapsed: float, phase_timings: dict
    ) -> dict:
        """Buduje pełny dokument wynikowy JSON łączący wyniki wszystkich wysp."""
        best = min(results, key=lambda x: x["distance"])
        distances = [r["distance"] for r in results]
        diversity = self._diversity(results)
        return {
            "metadata": {
                **self.metadata,
                "worker_count": len(self.workers),
                "cities": self.matrix.size,
                "elapsed_seconds": elapsed,
                "phase_timings": phase_timings,
                "migration_strategy": self.ga_config.migration_strategy,
            },
            "ga_config": self.ga_config.as_dict(),
            "summary": {
                "best_distance": best["distance"],
                "best_worker_id": best["worker_id"],
                "best_path": best["path"],
                "min_distance": min(distances),
                "mean_distance": statistics.mean(distances),
                "max_distance": max(distances),
            },
            "diversity": diversity,
            "islands": results,
        }

    def _save_results(self, document: dict) -> None:
        """Zapisuje dokument wynikowy do pliku JSON pod wskazaną ścieżką."""
        path = Path(self.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[Master] Wyniki zapisane do {self.output}")

    def _print_summary(self, document: dict) -> None:
        """Wydrukuje w konsoli zbiorczą tabelę wyników."""
        meta = document["metadata"]
        s = document["summary"]
        div = document["diversity"]
        pt = meta.get("phase_timings", {})
        total = meta["elapsed_seconds"]
        print("\n================ GLOBALNY NAJLEPSZY WYNIK ================")
        print(f"ID uruchomienia    : {meta.get('run_id', 'n/a')}")
        print(f"Znalazł kontener   : {s['best_worker_id']}")
        print(f"Najkrótszy dystans : {s['best_distance']:.4f}")
        print(f"Optymalna trasa    : {' -> '.join(s['best_path'])}")
        print("──────────────── Podsumowanie wysp ──────────────────────────")
        print(f"Liczba wysp        : {len(document['islands'])}")
        print(f"Strategia migracji : {meta['migration_strategy']}")
        print(f"Liczba miast       : {meta['cities']}")
        print(
            f"Dystans min/śr/max : "
            f"{s['min_distance']:.2f} / {s['mean_distance']:.2f} / {s['max_distance']:.2f}"
        )
        print(f"Unikalne trasy     : {div['unique_best_routes']}")
        print(f"Różnorodność kraw. : {div['mean_pairwise_edge_distance']:.4f} (śr)")
        print("──────────────── Czasy faz ──────────────────────────────────")
        if pt:
            print(f"Prowizjonowanie  : {pt.get('provision_seconds',  0):.2f}s")
            print(f"Przesyłanie kodu : {pt.get('distribute_seconds', 0):.2f}s")
            print(f"Wykonanie GA     : {pt.get('execute_seconds',    0):.2f}s")
        print(f"Łącznie          : {total:.2f}s")
        print("==============================================================")
        print(
            f"\nGOTOWE run_id={meta.get('run_id', 'n/a')} "
            f"scenariusz={meta.get('scenario_name', 'n/a')} "
            f"wyspy={len(document['islands'])} "
            f"miasta={meta['cities']} "
            f"strategia={meta['migration_strategy']} "
            f"najlepszy_dystans={s['best_distance']:.6f} "
            f"różnorodność_kraw_śr={div['mean_pairwise_edge_distance']:.6f} "
            f"czas_sekundy={total:.6f}"
            + (f" wyjście={self.output}" if self.output else "")
        )

    # -- Główny punkt wejścia --
    def run(self) -> dict:
        """
        Uruchomia pełny potok: przygotowanie kontenerów → dystrybucja → GA → [cleanup].

        Zwraca dokument wynikowy jako słownik Pythona.
        """
        strategy = self.ga_config.migration_strategy
        print(
            f"--- Węzeł master inicjalizuje zadanie TSP: "
            f"{self.matrix.size} miast, "
            f"{len(self.workers)} wyspa(y), "
            f"strategia={strategy} ---"
        )

        t_total_start = time.time()

        # -- Faza 1: przygotowanie kontenerów --
        t0 = time.time()
        self.lxd.provision(self.workers)
        t_provision = time.time() - t0

        # -- Faza 2: Dystrybucja kodu --
        t0 = time.time()
        self._distribute_common()
        t_distribute = time.time() - t0

        # -- Faza 3: Wykonanie GA --
        t0 = time.time()
        if strategy == "none":
            print("[Master] Uruchamianie wyspowego GA (jednorazowe)...")
            results = self._execute_single()
        else:
            print(
                f"[Master] Uruchamianie wyspowego GA "
                f"({self.ga_config.generations} gen, "
                f"{self.ga_config.migration_interval} gen/rundę, "
                f"strategia={strategy})..."
            )
            results = self._execute_rounds()
        t_execute = time.time() - t0

        t_total = time.time() - t_total_start

        if not results:
            print("[Master] Krytyczny błąd: brak prawidłowych wyników z klastra.")
            return {}

        phase_timings = {
            "provision_seconds": t_provision,
            "distribute_seconds": t_distribute,
            "execute_seconds": t_execute,
            "total_seconds": t_total,
        }

        document = self._build_result_document(results, t_total, phase_timings)
        if self.output:
            self._save_results(document)
        self._print_summary(document)

        # -- Faza 4: Usuwanie kontenerów (opcjonalne) --
        if self.cleanup:
            self.lxd.delete_workers(self.workers)

        return document
