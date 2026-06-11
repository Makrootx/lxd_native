"""
ga_config_model.py — Typowany model konfiguracji GA.

GAConfigModel waliduje wszystkie parametry algorytmu genetycznego
i udostępnia metody konwersji do słowników używanych przez pracowników.
Obsługuje zarówno pydantic v2 (model_validator) jak i pydantic v1 (root_validator).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# -- Obsługa pydantic v1/v2 --
try:
    from pydantic import model_validator

    _HAS_MODEL_VALIDATOR = True
except ImportError:  # pydantic v1
    from pydantic import root_validator

    _HAS_MODEL_VALIDATOR = False

from config.config import GA_DEFAULTS


# -- Model konfiguracji GA --
class GAConfigModel(BaseModel):
    """
    Typowany model konfiguracji algorytmu genetycznego.

    Walidacja przez pydantic zapewnia:
      - zakresy numeryczne (ge/le)
      - dozwolone wartości strategii migracji (Literal)
      - spójność między polami (elite < population_size, tournament <= population_size)
    """

    population_size: int = Field(default=GA_DEFAULTS["population_size"], ge=4)
    generations: int = Field(default=GA_DEFAULTS["generations"], ge=1)
    mutation: float = Field(default=GA_DEFAULTS["mutation"], ge=0.0, le=1.0)
    elite: int = Field(default=GA_DEFAULTS["elite"], ge=1)
    tournament: int = Field(default=GA_DEFAULTS["tournament"], ge=2)
    two_opt_attempts: int = Field(default=GA_DEFAULTS["two_opt_attempts"], ge=0)
    migration_strategy: Literal["none", "ring", "global-best"] = GA_DEFAULTS[
        "migration_strategy"
    ]
    migration_interval: int = Field(default=GA_DEFAULTS["migration_interval"], ge=1)
    immigrants: int = Field(default=GA_DEFAULTS["immigrants"], ge=0)
    report_interval: int = Field(default=GA_DEFAULTS["report_interval"], ge=1)
    debug_routes: bool = GA_DEFAULTS["debug_routes"]
    seed: int = GA_DEFAULTS["seed"]

    class Config:
        extra = "forbid"

    # -- Walidacja krzyżowa pól --
    if _HAS_MODEL_VALIDATOR:

        @model_validator(mode="after")
        def _cross_field_checks(self) -> "GAConfigModel":
            if self.elite >= self.population_size:
                raise ValueError("elite musi być < population_size")
            if self.tournament > self.population_size:
                raise ValueError("tournament musi być <= population_size")
            return self

    else:

        @root_validator(skip_on_failure=True)
        def _cross_field_checks(cls, values: dict) -> dict:
            """Walidacja krzyżowa dla pydantic v1."""
            pop = values.get("population_size")
            elite = values.get("elite")
            tournament = values.get("tournament")

            if pop is not None and elite is not None and elite >= pop:
                raise ValueError("elite musi być < population_size")
            if pop is not None and tournament is not None and tournament > pop:
                raise ValueError("tournament musi być <= population_size")

            return values

    # -- Eksport do słownika --
    def worker_task_dict(self) -> dict:
        """Zwraca tylko pola GA potrzebne dla workerów."""
        return {
            "population_size": self.population_size,
            "generations": self.generations,
            "mutation": self.mutation,
            "elite": self.elite,
            "tournament": self.tournament,
            "two_opt_attempts": self.two_opt_attempts,
            "report_interval": self.report_interval,
            "debug_routes": self.debug_routes,
            "seed": self.seed,
            "immigrants": self.immigrants,
        }

    def as_dict(self) -> dict:
        """Eksport do słownika zgodny z pydantic v1 i v2."""
        if hasattr(self, "model_dump"):
            return self.model_dump()
        return self.dict()
