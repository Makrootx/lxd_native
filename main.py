#!/usr/bin/env python3
"""
main.py — Punkt wejścia rozproszonego orkiestratora TSP (pylxd v2).

Przekazuje sterowanie do modułu cli.main(), który obsługuje
parsowanie argumentów, ładowanie konfiguracji i uruchomienie orkiestratora.

Użycie
------
    python3 main.py --help
    python3 main.py --workers worker-1,worker-2,worker-3 \\
                    --generations 2000 --population 100 \\
                    --migration-strategy ring \\
                    --output results/run-001.json \\
                    --metadata-run-id lxd-run-001 \\
                    --metadata-scenario-name 3-containers
"""

from cli import main

if __name__ == "__main__":
    main()
