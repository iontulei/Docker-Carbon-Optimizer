"""Carbon estimation for Docker image size savings.

Uses the Aslan et al. (2018) network energy model with IEA/Ember grid
carbon intensity data.  Sources:
  - Aslan et al. "Electricity Intensity of Internet Data Transmission" (2018)
  - IEA Emissions Factors 2024/2025
  - Ember Global Electricity Review 2024
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dco.config import (
    DEFAULT_GRID_INTENSITY as _DEFAULT_GRID_G_CO2_PER_KWH,
)
from dco.config import (
    DEFAULT_PULLS_PER_MONTH as _DEFAULT_PULLS_PER_MONTH,
)
from dco.config import (
    DEFAULT_REGION as _DEFAULT_REGION,
)
from dco.config import (
    HALVING_PERIOD_YEARS as _HALVING_PERIOD_YEARS,
)
from dco.config import (
    NETWORK_KWH_PER_GB_2015 as _ASLAN_BASELINE_KWH_PER_GB,
)

_ASLAN_BASELINE_YEAR = 2015

# ---------------------------------------------------------------------------
# Grid intensity data (loaded once from JSON)
# ---------------------------------------------------------------------------

_GRID_FILE = Path(__file__).resolve().parent.parent / "data" / "grid_intensity.json"
_grid_cache: dict[str, float] | None = None


def _load_grid_intensity() -> dict[str, float]:
    """Load grid_intensity.json and return ``{region_code: gCO2/kWh}``."""
    global _grid_cache
    if _grid_cache is not None:
        return _grid_cache
    raw = json.loads(_GRID_FILE.read_text(encoding="utf-8"))
    _grid_cache = {
        k: v["gco2_per_kwh"]
        for k, v in raw.items()
        if isinstance(v, dict) and "gco2_per_kwh" in v
    }
    return _grid_cache


def get_grid_intensity() -> dict[str, float]:
    """Public accessor - returns ``{region_code: gCO2_per_kWh}``."""
    return dict(_load_grid_intensity())


# Keep a module-level alias for backward compat (used by __init__.py export).
GRID_INTENSITY = property(lambda _: get_grid_intensity())  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CarbonEstimate:
    size_saved_gb: float
    pulls_per_month: float
    network_kwh_per_gb: float
    grid_g_co2_per_kwh: float
    co2_kg_per_month: float


# ---------------------------------------------------------------------------
# Estimator
# ---------------------------------------------------------------------------


class CarbonEstimator:
    """Estimates monthly CO2 savings from reducing Docker image size.

    Formula (from Aslan et al. 2018 + IEA 2023):
        CO2_per_month = size_saved_GB * pulls_per_month
                        * network_kWh_per_GB * grid_gCO2_per_kWh / 1000
    """

    def __init__(
        self,
        pulls_per_month: float = _DEFAULT_PULLS_PER_MONTH,
        region: str = "world",
        reference_year: int | None = None,
    ) -> None:
        self.pulls_per_month = pulls_per_month
        grid = _load_grid_intensity()
        self.grid_g_co2_per_kwh = grid.get(
            region.lower(), _DEFAULT_GRID_G_CO2_PER_KWH
        )
        self.network_kwh_per_gb = self._network_kwh_per_gb(
            reference_year if reference_year is not None else date.today().year
        )

    @staticmethod
    def _network_kwh_per_gb(year: int) -> float:
        """Return network energy intensity (kWh/GB) for the given year.

        Applies Aslan et al. 2018 model: baseline 0.06 kWh/GB in 2015,
        halving every 2 years.
        """
        years_elapsed = year - _ASLAN_BASELINE_YEAR
        halvings = years_elapsed / _HALVING_PERIOD_YEARS
        return _ASLAN_BASELINE_KWH_PER_GB * (0.5 ** halvings)

    def estimate(self, size_saved_gb: float) -> CarbonEstimate:
        """Return a CarbonEstimate for the given image size reduction in GB."""
        co2_kg = (
            size_saved_gb
            * self.pulls_per_month
            * self.network_kwh_per_gb
            * self.grid_g_co2_per_kwh
            / 1000
        )
        return CarbonEstimate(
            size_saved_gb=size_saved_gb,
            pulls_per_month=self.pulls_per_month,
            network_kwh_per_gb=self.network_kwh_per_gb,
            grid_g_co2_per_kwh=self.grid_g_co2_per_kwh,
            co2_kg_per_month=co2_kg,
        )


# ---------------------------------------------------------------------------
# Convenience wrapper (returns grams, accepts MB - matches old output.py API)
# ---------------------------------------------------------------------------


def estimate_co2_grams(
    size_saved_mb: float,
    pulls_per_month: float = _DEFAULT_PULLS_PER_MONTH,
    region: str = _DEFAULT_REGION,
) -> float:
    """Estimate CO2 savings in **grams** per month.

    Thin wrapper around :class:`CarbonEstimator` that accepts size in MB
    and returns grams (the unit used by the output formatters).
    """
    estimator = CarbonEstimator(pulls_per_month, region)
    result = estimator.estimate(size_saved_mb / 1000)
    return result.co2_kg_per_month * 1000
