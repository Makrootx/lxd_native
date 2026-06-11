"""
timing.py — Pomiar czasu trwania etapów ewolucji (kontener LXD).

Klasa StageTimer opakowuje wybraną funkcję zegarową (np. time.perf_counter)
i mierzy czas wywołania dowolnej funkcji przekazanej jako argument.
Używana w runner.py do oddzielnego mierzenia czasu ewolucji od reszty operacji.
"""

from __future__ import annotations

from collections.abc import Callable


# -- Klasa narzędziowa --
class StageTimer:
    """Mierzy czas trwania etapów obliczeniowych za pomocą dostarczonego zegara."""

    def __init__(self, now: Callable[[], float]) -> None:
        # Funkcja zegarowa: musi być monotoniczna (np. time.perf_counter).
        self._now = now

    def measure(self, action: Callable[[], object]) -> tuple[object, float]:
        """Wywołaj *action* i zwróć ``(wynik, czas_wykonania_w_sekundach)``."""
        start = self._now()
        result = action()
        return result, self._now() - start

    def measure_void(self, action: Callable[[], None]) -> float:
        """Wywołaj *action* i zwróć czas jej wykonania w sekundach."""
        start = self._now()
        action()
        return self._now() - start
