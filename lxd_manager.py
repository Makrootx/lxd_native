"""
lxd_manager.py — Zarządzanie infrastrukturą LXD przez pylxd.

Architektura
------------
``LXDClient``
    Lekki, bezpieczny wątkowo wrapper wokół pojedynczego połączenia
    ``pylxd.Client``. Udostępnia wyłącznie prymitywy: execute, I/O plików,
    zapytania o stan, CRUD kontenerów. Brak logiki orkiestracyjnej.

``LXDOrchestrator``
    Zarządca cyklu życia kontenerów zbudowany na ``LXDClient``.
    Posiada globalny ``ThreadPoolExecutor``, dzięki czemu przygotowanie kontenerów,
    dystrybucja plików i usuwanie są ograniczone jednym limitem współbieżności
    niezależnie od liczby żądanych pracowników.

    Każde przesłane zadanie otrzymuje *własny* ``LXDClient`` (własne połączenie
    pylxd), aby uniknąć problemów z współdzieleniem WebSocket przy długich
    operacjach jak instalacje apt.

Używane elementy API pylxd
--------------------------
* ``pylxd.Client()``                        — połączenie z daemonem LXD
* ``client.containers.get(name)``           — odszukanie istniejącego kontenera
* ``client.containers.create(cfg, wait)``   — tworzenie nowego kontenera
* ``instance.start(wait=True)``             — uruchomienie zatrzymanego kontenera
* ``instance.execute(cmd)``                 — uruchomienie polecenia → ExecuteResult
* ``instance.files.put(path, data)``        — zapis bajtów do systemu plików kontenera
* ``instance.files.get(path)``              — odczyt bajtów z systemu plików kontenera
* ``instance.state()``                      — stan: status, sieć, CPU, pamięć
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import pylxd
import pylxd.exceptions
import urllib3

from config.config import LXD_CA, LXD_CERT, LXD_ENDPOINT, LXD_KEY, LXD_TARGET

# -- Stałe pomocnicze --
# Błędy sieciowe, które uzasadniają ponowną próbę execute().
_TRANSIENT_ERRS = (BrokenPipeError, ConnectionResetError)


def _install_ws4py_exception_filter() -> None:
    """
    Wycisza niegroźny wyjątek ws4py na Python 3.14:
    "ValueError: I/O operation on closed epoll object" z wątku WebSocketManager.

    To błąd porządkowania zasobów w bibliotece ws4py, który nie wpływa
    na wynik obliczeń. Wszystkie inne wyjątki wątków pozostają raportowane.
    """
    if getattr(threading, "_lxd_ws4py_filter_installed", False):
        return

    previous_hook = threading.excepthook

    def _hook(args: threading.ExceptHookArgs) -> None:
        msg = str(args.exc_value or "")
        if (
            getattr(args.thread, "name", "") == "WebSocketManager"
            and isinstance(args.exc_value, ValueError)
            and "closed epoll object" in msg
        ):
            return
        previous_hook(args)

    threading.excepthook = _hook
    threading._lxd_ws4py_filter_installed = True


_install_ws4py_exception_filter()


# -- Fabryka klienta pylxd --
def _new_pylxd_client() -> pylxd.Client:
    """
    Stwarza nowy ``pylxd.Client``.

    Używa zdalnego endpointu i certyfikatów TLS z config gdy ustawione;
    w przeciwnym razie łączy się przez lokalny socket Unix.
    """
    if LXD_ENDPOINT:
        cert = (LXD_CERT, LXD_KEY) if LXD_CERT and LXD_KEY else None
        ca_raw = str(LXD_CA).strip().lower() if LXD_CA else ""
        if ca_raw in {"false", "0", "no"}:
            # Tryb deweloperski: ukrywa tylko warning o niezweryfikowanym HTTPS.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            verify: str | bool = False
        else:
            verify = LXD_CA if LXD_CA else True
        return pylxd.Client(endpoint=LXD_ENDPOINT, cert=cert, verify=verify)
    return pylxd.Client()


# -- LXDClient — niskopoziomowe prymitywy --
class LXDClient:
    """
    Bezpieczny wątkowo wrapper wokół pojedynczego połączenia ``pylxd.Client``.

    Każda metoda publiczna komunikująca się z daemonem blokuje ``_lock``,
    dzięki czemu wiele wątków orkiestratora może współdzielić jedną instancję
    bez wyścigów na WebSocket. Dla długich operacji (instalacje apt, duże pliki)
    orkiestrator tworzy *dedykowany* ``LXDClient`` per wątek — ``LXDOrchestrator._dedicated()``.
    """

    def __init__(self) -> None:
        self._client: pylxd.Client | None = None
        self._lock = threading.Lock()

    # -- Połączenie --
    @property
    def _conn(self) -> pylxd.Client:
        """Inicjalizuje leniwie i zwraca wewnętrzny klient pylxd."""
        with self._lock:
            if self._client is None:
                self._client = _new_pylxd_client()
            return self._client

    def _instance(self, name: str):
        """Zwraca obiekt kontenera pylxd dla *name*."""
        return self._conn.containers.get(name)

    # -- Wykonywanie poleceń --
    def execute(
        self, container: str, cmd: list[str], retries: int = 3
    ) -> tuple[str, str]:
        """
        Uruchamia *cmd* wewnątrz *container* przez ``instance.execute()``.

        Zwraca ``(stdout, stderr)`` jako przycinane ciągi znaków.
        Ponawia przy przejściowych błędach WebSocket / połączenia
        z wykładniczym cofaniem (2s, 4s).
        """
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                res = self._instance(container).execute(cmd)
                return (res.stdout or "").strip(), (res.stderr or "").strip()
            except _TRANSIENT_ERRS as exc:
                last_exc = exc
            except pylxd.exceptions.LXDAPIException as exc:
                msg = repr(exc)
                if "operation not found" in msg.lower() or "not found" in msg.lower():
                    last_exc = exc
                else:
                    raise
            if attempt < retries:
                time.sleep(2 * attempt)  # cofanie: 2s, 4s

        raise RuntimeError(
            f"execute({container}, {cmd!r}) nie powiodło się po {retries} próbach: {last_exc!r}"
        )

    # -- I/O plików --
    def push_bytes(
        self,
        container: str,
        remote_path: str,
        data: bytes,
        mode: int = 0o644,
    ) -> None:
        """Zapisuje surowe bajty *data* pod *remote_path* wewnątrz *container*."""
        self._instance(container).files.put(remote_path, data, mode=mode)

    def push_file(self, container: str, local_path: str, remote_path: str) -> None:
        """
        Zapisuje *local_path* pod *remote_path* wewnątrz *container*.
        Uprawnienia pliku są zachowywane.
        """
        mode = os.stat(local_path).st_mode & 0o777
        with open(local_path, "rb") as fh:
            data = fh.read()
        self.push_bytes(container, remote_path, data, mode=mode)

    def push_directory(self, container: str, local_dir: str, remote_dir: str) -> None:
        """
        Rekurencyjnie wgrywa wszystkie pliki z *local_dir* do *remote_dir*,
        zachowując strukturę ścieżek względnych.
        """
        local_root = Path(local_dir)
        parents: set[str] = set()
        files: list[tuple[Path, str]] = []

        for file_path in sorted(local_root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(local_root)
            remote_file = f"{remote_dir}/{rel.as_posix()}"
            parents.add(str(Path(remote_file).parent))
            files.append((file_path, remote_file))

        # Stwarza wszystkie katalogi docelowe jednym poleceniem mkdir -p.
        if parents:
            self.execute(container, ["mkdir", "-p"] + sorted(parents))

        for file_path, remote_file in files:
            self.push_file(container, str(file_path), remote_file)

    # -- Stan kontenera --
    def get_status(self, name: str) -> str:
        """
        Zwraca ciąg statusu kontenera (np. ``'running'``, ``'stopped'``).
        Koniecznie jest odświeżenie stanu przez API - ``.state()`` - zamiast polegać na cache pylxd.
        """
        return self._instance(name).state().status.lower()

    def exists(self, name: str) -> bool:
        """Zwraca ``True`` jeśli kontener o nazwie *name* istnieje."""
        try:
            self._conn.containers.get(name)
            return True
        except pylxd.exceptions.NotFound:
            return False

    def cluster_members(self) -> list[str]:
        """
        Zwraca posortowaną listę nazw węzłów klastra LXD.
        Zwraca pustą listę gdy daemon nie jest skonfigurowany jako klaster.
        """
        try:
            return sorted(m.server_name for m in self._conn.cluster.members.all())
        except Exception:
            return []

    # -- CRUD kontenerów --
    def create(
        self, name: str, image: str = "debian/12", target: str | None = None
    ) -> None:
        """
        Stwarza nowy kontener z *image* na węźle klastra *target*.

        Zawsze pobiera z serwera canonical simplestreams — każdy węzeł
        pobiera i buforuje obraz niezależnie, co zapobiega błędom
        "Unsupported compression" przy transferach fingerprint między węzłami.

        Używa surowego endpointu ``/1.0/containers`` POST, omijając błąd
        pylxd gdzie ``wait_for_operation`` crashuje przy operacjach cross-node.
        Start jest wysyłany bez oczekiwania; wywołujący używa _wait_for_running.
        """
        _alias_map = {"debian/12": "debian/bookworm"}
        source: dict = {
            "type": "image",
            "alias": _alias_map.get(image, image),
            "server": "https://images.lxd.canonical.com",
            "protocol": "simplestreams",
            "mode": "pull",
        }
        params = {"target": target} if target else {}
        resp = self._conn.api.containers.post(
            json={"name": name, "source": source}, params=params
        )
        op_url = (resp.json() or {}).get("operation", "")
        if op_url:
            self._wait_operation(op_url, timeout=300)

        inst = self._conn.containers.get(name)
        try:
            inst.start(wait=False)
        except Exception:
            pass  # kontener może już startować

    def delete(self, name: str) -> None:
        """Zatrzymuje i usuwa kontener *name*. Brak operacji jeśli kontener nie istnieje."""
        try:
            instance = self._instance(name)
        except pylxd.exceptions.NotFound:
            return
        try:
            if instance.status.lower() != "stopped":
                instance.stop(wait=True)
        except pylxd.exceptions.LXDAPIException:
            pass
        instance.delete(wait=True)

    # -- Wewnętrzne: odpytywanie operacji --
    def _wait_operation(self, op_url: str, timeout: int = 300) -> None:
        """
        Odpytuje URL operacji LXD do osiągnięcia statusu Success lub Failure.

        Omija ``client.operations.wait_for_operation()`` które jest zepsute
        w starszych wersjach pylxd dla operacji cross-node w klastrze.
        """
        op_id = op_url.rstrip("/").rsplit("/", 1)[-1]
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = self._conn.api.operations[op_id].get()
                meta = (resp.json() or {}).get("metadata") or {}
                status = meta.get("status", "")
                if status == "Success":
                    return
                if status == "Failure":
                    err = meta.get("err") or str(meta.get("status_code", "nieznany"))
                    raise RuntimeError(f"Operacja LXD {op_id} zakończona błędem: {err}")
            except RuntimeError:
                raise
            except Exception:
                pass  # przejściowy błąd — ponów
            time.sleep(2)
        raise TimeoutError(f"Operacja LXD {op_id} przekroczyła limit czasu {timeout}s")


# -- LXDOrchestrator — zarządzanie cyklem życia kontenerów --
class LXDOrchestrator:
    """
    Zarządca cyklu życia kontenerów wysokiego poziomu.

    Posiada jeden ``ThreadPoolExecutor`` współdzielony przez wszystkie operacje,
    dzięki czemu łączna liczba jednoczesnych połączeń LXD jest ograniczona
    przez *concurrency* niezależnie od liczby żądanych pracowników.

    Każde przesłane zadanie otrzymuje *własny* ``LXDClient`` (własne połączenie
    pylxd), aby uniknąć problemów z współdzieleniem WebSocket przy długich
    operacjach takich jak instalacje apt.
    """

    def __init__(self, concurrency: int = 6) -> None:
        self.concurrency = concurrency
        # Wspólny klient dla tanich, szybkich operacji (sprawdzanie istnienia, stanu).
        self._shared = LXDClient()
        # Globalny pool — przez niego przechodzi cała praca równoległa.
        self._pool = ThreadPoolExecutor(max_workers=concurrency)

    # -- Dedykowany klient per zadanie --
    @staticmethod
    def _dedicated() -> LXDClient:
        """Zwraca nowy ``LXDClient`` do wyłącznego użytku przez jeden wątek zadania."""
        return LXDClient()

    # -- Oczekiwanie na kontenera --
    def _wait_for_running(
        self, client: LXDClient, name: str, timeout: int = 120
    ) -> None:
        """
        Czeka aż *name* osiągnie stan ``running``, następnie potwierdza sieć.

        Sprawdzenie DNS używa POSIX sh + znacznika tekstowego, co działa
        nawet gdy ``getent`` jest niedostępne w minimalnych image dla kontenerów.
        """
        print(f"  [prowizjonowanie] Oczekiwanie na stan Running dla {name}...")
        deadline = time.time() + timeout
        started = False
        while time.time() < deadline:
            status = client.get_status(name)
            if status == "running":
                break
            if status == "stopped" and not started:
                # Uruchamiaj start tylko raz; kontener może po prostu startować.
                try:
                    client._instance(name).start(wait=False)
                    started = True
                    print(
                        f"  [prowizjonowanie] {name} jest zatrzymany — uruchamianie..."
                    )
                except Exception:
                    pass
            time.sleep(2)
        else:
            raise TimeoutError(
                f"Kontener {name} nie osiągnął stanu Running w ciągu {timeout}s"
            )

        print(f"  [prowizjonowanie] Oczekiwanie na sieć w {name}...")
        net_deadline = time.time() + 60
        while time.time() < net_deadline:
            # Używamy POSIX sh + jawnego znacznika — działa nawet gdy getent
            # jest nieobecne w bardzo minimalnych obrazach (np. debian/bookworm base).
            stdout, _ = client.execute(
                name,
                [
                    "sh",
                    "-c",
                    (
                        "if command -v getent >/dev/null 2>&1 && "
                        "getent hosts deb.debian.org >/dev/null 2>&1; "
                        "then echo OK; else echo NO; fi"
                    ),
                ],
            )
            if stdout.strip() == "OK":
                return
            time.sleep(3)
        # Jesli DNS nie odpowiada — próbuje naprawić.
        self._fix_dns(client, name)

    def _fix_dns(self, client: LXDClient, container: str) -> None:
        """Zapisuje działający ``resolv.conf`` jeśli DNS jest uszkodzony."""
        stdout, _ = client.execute(
            container,
            [
                "sh",
                "-c",
                (
                    "if command -v getent >/dev/null 2>&1 && "
                    "getent hosts deb.debian.org >/dev/null 2>&1; "
                    "then echo OK; else echo NO; fi"
                ),
            ],
        )
        if stdout.strip() == "OK":
            return
        print(
            f"  [prowizjonowanie] DNS uszkodzony w {container} — zapisywanie resolv.conf..."
        )
        client.push_bytes(
            container,
            "/etc/resolv.conf",
            b"nameserver 8.8.8.8\nnameserver 1.1.1.1\n",
            mode=0o644,
        )
        # Sprawdza ponownie po naprawieniu.
        stdout, _ = client.execute(
            container,
            [
                "sh",
                "-c",
                (
                    "if command -v getent >/dev/null 2>&1 && "
                    "getent hosts deb.debian.org >/dev/null 2>&1; "
                    "then echo OK; else echo NO; fi"
                ),
            ],
        )
        if stdout.strip() != "OK":
            raise RuntimeError(
                f"DNS nadal uszkodzony w {container} po zapisaniu resolv.conf. "
                "Upewnij się że lxdbr0 jest podłączone do kontenera."
            )

    def _ensure_python3(self, client: LXDClient, container: str) -> None:
        """Instaluje python3 wewnątrz *container* jeśli jeszcze nie jest dostępny."""
        stdout, _ = client.execute(container, ["python3", "--version"])
        if stdout:
            print(f"  [prowizjonowanie] python3 obecny w {container}: {stdout}")
            return

        print(f"  [prowizjonowanie] Instalowanie python3 w {container}...")
        # Czyści listy apt — obcięte pliki Packages powodują błędy aktualizacji.
        client.execute(
            container,
            ["sh", "-c", "rm -rf /var/lib/apt/lists/* /var/lib/apt/lists/partial/*"],
        )
        _, stderr = client.execute(
            container,
            ["sh", "-c", "DEBIAN_FRONTEND=noninteractive apt-get update -y 2>&1"],
        )
        if "E: " in stderr:
            raise RuntimeError(f"apt-get update nieudany w {container}: {stderr}")

        _, stderr = client.execute(
            container,
            [
                "sh",
                "-c",
                "DEBIAN_FRONTEND=noninteractive apt-get install -y python3 2>&1",
            ],
        )
        if "E: " in stderr:
            raise RuntimeError(f"Instalacja python3 nieudana w {container}: {stderr}")

        stdout, _ = client.execute(container, ["python3", "--version"])
        if not stdout:
            raise RuntimeError(
                f"python3 nadal niedostępny w {container} po instalacji."
            )

    # -- Zadanie przygotowania jednego kontenera --
    def _provision_task(self, worker: str, target: str | None) -> None:
        """
        Pełna sekwencja przygotowania kontenera wykonana wewnątrz puli wątków.

        Używa *dedykowanego* ``LXDClient``, dzięki czemu to zadanie nigdy
        nie współdzieli WebSocket z innymi równoległymi zadaniami.
        """
        client = self._dedicated()
        if client.exists(worker):
            print(f"  [prowizjonowanie] {worker} już istnieje — pomijanie tworzenia.")
        else:
            loc = f" → {target}" if target else ""
            print(f"  [prowizjonowanie] Tworzenie {worker} (debian/12){loc}...")
            client.create(worker, "debian/12", target=target)

        self._wait_for_running(client, worker)
        self._fix_dns(client, worker)
        self._ensure_python3(client, worker)

    # -- Równoległe przygotowanie kontenerów --
    def provision(self, workers: Iterable[str]) -> None:
        """
        Przygotowuje wszystkich *workers* równolegle, do ``self.concurrency`` jednocześnie.

        Wszystkie futures przesyłane są do wspólnej puli; wyniki zbierane
        przez ``as_completed`` — błędy pojawiają się natychmiast gdy wystąpią.
        Rzuca ``RuntimeError`` (z listą błędów) jeśli jakiś pracownik nie powiedzie się.
        """
        worker_list = list(workers)
        members = self._shared.cluster_members()
        if members:
            print(f"[Orkiestrator] Węzły klastra LXD: {members}")
        print(
            f"[Orkiestrator] Przygotowywanie {len(worker_list)} pracownika(ów) "
            f"(rozmiar puli: {self.concurrency})..."
        )

        # Użyj węzła docelowego z konfiguracji lub auto-wykryj.
        target: str | None = LXD_TARGET if LXD_TARGET else None

        futures = {
            self._pool.submit(self._provision_task, w, target): w for w in worker_list
        }
        errors: dict[str, Exception] = {}
        for future in as_completed(futures):
            worker = futures[future]
            exc = future.exception()
            if exc:
                print(f"  [przygotowywanie] BŁĄD w {worker}: {exc}")
                errors[worker] = exc

        if errors:
            names = ", ".join(errors)
            raise RuntimeError(f"Przygotowywanie nieudane dla: {names}")
        print("[Orkiestrator] Wszyscy pracownicy gotowi.\n")

    # -- Dystrybucja plików --
    def push_files(self, workers: Iterable[str], files: list[tuple[str, str]]) -> None:
        """
        Zapisuje pary ``[(ścieżka_lokalna, ścieżka_zdalna), ...]`` do wszystkich
        *workers* równolegle przez wspólną pulę.
        """

        def _task(worker: str) -> None:
            client = self._dedicated()
            for local, remote in files:
                client.push_file(worker, local, remote)

        list(self._pool.map(_task, list(workers)))

    def push_directory_to_all(
        self, workers: Iterable[str], local_dir: str, remote_dir: str
    ) -> None:
        """Wgrywa *local_dir* do *remote_dir* na każdym pracowniku przez wspólną pulę."""

        def _task(worker: str) -> None:
            self._dedicated().push_directory(worker, local_dir, remote_dir)

        list(self._pool.map(_task, list(workers)))

    # -- Wykonanie skryptu pracownika --
    def run_worker_script(
        self, container: str, script: str = "/root/worker.py"
    ) -> tuple[str, str, str]:
        """
        Uruchamia skrypt Python wewnątrz *container*.
        Zwraca ``(nazwa_kontenera, stdout, stderr)``.
        """
        stdout, stderr = self._shared.execute(container, ["python3", script])
        return container, stdout, stderr

    def run_worker_scripts(
        self, workers: Iterable[str], script: str = "/root/worker.py"
    ) -> list[tuple[str, str, str]]:
        """
        Uruchamia *script* na wszystkich *workers* równolegle przez wspólną pulę.
        Zwraca listę ``(nazwa_kontenera, stdout, stderr)``.
        """
        futures = {
            self._pool.submit(self.run_worker_script, w, script): w for w in workers
        }
        results = []
        for future in as_completed(futures):
            results.append(future.result())
        return results

    # -- Sprzątanie --
    def _delete_task(self, worker: str) -> None:
        """Usuwa jeden kontener; dedykowany klient zapobiega problemom ze współdzieleniem."""
        self._dedicated().delete(worker)
        print(f"  [sprzątanie] Usunięto {worker}")

    def delete_workers(self, workers: Iterable[str]) -> None:
        """
        Zatrzymuje i usuwa wszystkich *workers* równolegle przez wspólną pulę.
        Błędy są logowane, ale nie przerywają usuwania pozostałych.
        """
        worker_list = list(workers)
        print(f"[Orkiestrator] Usuwanie {len(worker_list)} pracownika(ów)...")
        futures = {self._pool.submit(self._delete_task, w): w for w in worker_list}
        for future in as_completed(futures):
            worker = futures[future]
            exc = future.exception()
            if exc:
                print(f"  [sprzątanie] OSTRZEŻENIE: nie można usunąć {worker}: {exc}")
        print("[Orkiestrator] Sprzątanie zakończone.\n")

    # -- Zarządzanie zasobami --
    def shutdown(self, wait: bool = True) -> None:
        """Zamyka pulę wątków. Wywoływane gdy orkiestrator zakończy pracę."""
        self._pool.shutdown(wait=wait)

    def __enter__(self) -> "LXDOrchestrator":
        return self

    def __exit__(self, *_) -> None:
        self.shutdown()
