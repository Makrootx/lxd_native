"""
config.py — Dane problemu i konfiguracja klastra LXD.

Przy imporcie moduł:
  1. Wczytuje plik .env_lxd.
  2. Eksponuje ustawienia klastra jako stałe modułowe.
  3. Buduje (lub generuje) macierz odległości miast TSP.

"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import dotenv_values

from utils.config_utils import (
    DistanceMatrix,
)

# -- Wczytywanie .env_lxd --
# Preferuje plik z katalogu głównego repozytorium;
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = Path(os.getenv("LXD_ENV_FILE", _PROJECT_ROOT / ".env_lxd"))
if not _ENV_FILE.exists():
    _ENV_FILE = Path(__file__).resolve().parent / ".env_lxd"
_env = {
    key: str(value)
    for key, value in dotenv_values(_ENV_FILE).items()
    if value is not None
}


# -- Ustawienia klastra --
# Maksymalna liczba jednoczesnych operacji prowizjonowania/wykonania.
LXD_CONCURRENCY: int = int(_env.get("LXD_CONCURRENCY", "6"))

# Zdalne połączenie LXD (puste ciągi → lokalny socket Unix).
LXD_ENDPOINT: str = _env.get("LXD_ENDPOINT", "")
LXD_CERT: str = _env.get("LXD_CERT", "")
LXD_KEY: str = _env.get("LXD_KEY", "")
LXD_CA: str = _env.get("LXD_CA", "")

# Węzeł docelowy dla nowych kontenerów; pusty → automatyczny wybór.
LXD_TARGET: str = _env.get("LXD_TARGET", "")

# -- Wbudowane współrzędne nazwanych miast --
_COORDS: dict[str, tuple[float, float]] = {
    # partia 1 (oryginalne 30 miast)
    "a": (0, 0),
    "b": (12, 28),
    "c": (47, 11),
    "d": (63, 55),
    "e": (30, 72),
    "f": (85, 20),
    "g": (91, 68),
    "h": (55, 40),
    "i": (78, 90),
    "j": (20, 50),
    "k": (5, 85),
    "l": (40, 95),
    "m": (100, 45),
    "n": (70, 5),
    "o": (25, 15),
    "p": (50, 60),
    "q": (115, 80),
    "r": (88, 130),
    "s": (35, 115),
    "t": (8, 110),
    "u": (60, 150),
    "v": (130, 30),
    "w": (145, 100),
    "x": (110, 155),
    "y": (75, 175),
    "z": (20, 160),
    "a1": (155, 60),
    "b1": (170, 140),
    "c1": (50, 195),
    "d1": (100, 200),
    # partia 2
    "e1": (42, 42),
    "f1": (135, 170),
    "g1": (18, 135),
    "h1": (95, 110),
    "i1": (72, 35),
    "j1": (160, 85),
    "k1": (30, 185),
    "l1": (120, 15),
    "m1": (55, 125),
    "n1": (185, 50),
    "o1": (10, 60),
    "p1": (140, 200),
    "q1": (80, 210),
    "r1": (200, 120),
    "s1": (65, 180),
    "t1": (175, 170),
    "u1": (45, 145),
    "v1": (105, 95),
    "w1": (15, 200),
    "x1": (125, 130),
    "y1": (190, 10),
    "z1": (90, 220),
    # partia 3
    "a2": (220, 30),
    "b2": (240, 90),
    "c2": (210, 155),
    "d2": (255, 200),
    "e2": (230, 250),
    "f2": (280, 140),
    "g2": (300, 60),
    "h2": (265, 20),
    "i2": (295, 120),
    "j2": (245, 175),
    "k2": (215, 220),
    "l2": (275, 240),
    "m2": (300, 180),
    "n2": (285, 80),
    "o2": (310, 250),
    "p2": (320, 130),
    "q2": (330, 50),
    "r2": (340, 200),
    "s2": (305, 300),
    "t2": (250, 300),
    "u2": (195, 270),
    "v2": (160, 240),
    "w2": (135, 280),
    "x2": (350, 100),
    "y2": (360, 270),
    "z2": (370, 30),
    # partia 4
    "a3": (380, 160),
    "b3": (395, 230),
    "c3": (410, 80),
    "d3": (425, 300),
    "e3": (440, 150),
    "f3": (460, 40),
    "g3": (450, 220),
    "h3": (480, 110),
    "i3": (500, 270),
    "j3": (415, 380),
    "k3": (470, 350),
    "l3": (500, 420),
    "m3": (530, 180),
    "n3": (545, 350),
    "o3": (560, 80),
    "p3": (575, 250),
    "q3": (590, 420),
    "r3": (610, 140),
    "s3": (625, 320),
    "t3": (640, 50),
    "u3": (650, 230),
    "v3": (665, 400),
}


# -- Wbudowana macierz odległości --
# Macierz zbudowana z powyższych współrzędnych euklidesowych.
DISTANCE_MATRIX = DistanceMatrix.from_coordinates(_COORDS)


# -- Domyślne wartości parametrów GA --
GA_DEFAULTS: dict = {
    "generations": 1500,
    "population_size": 50,
    "mutation": 0.15,
    "elite": 2,
    "tournament": 4,
    "two_opt_attempts": 3,
    "migration_strategy": "none",
    "migration_interval": 50,
    "immigrants": 0,
    "report_interval": 50,
    "debug_routes": False,
    "seed": 42,
}


# -- Pozostałe wartości domyślne --
DEFAULT_WORKERS: int = 5
DEFAULT_CITIES: int = 0
DEFAULT_CITIES_SEED: int = 42
DEFAULT_CLEANUP: bool = False
