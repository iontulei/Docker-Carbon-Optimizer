"""Constants and default configuration for DCO."""

# Carbon model defaults
# Arbitrary fallback used when Docker Hub is unavailable and --pulls-per-month
# is not provided.  No authoritative source - chosen as a round number that
# represents a moderately popular image.
DEFAULT_PULLS_PER_MONTH = 100_000
DEFAULT_REGION = "world"
# World average grid carbon intensity (gCO2/kWh).
# Source: IEA Emissions Factors 2024/2025 - matches grid_intensity.json "world".
DEFAULT_GRID_INTENSITY = 445

# Aslan et al. (2018) network energy model
NETWORK_KWH_PER_GB_2015 = 0.06  # baseline kWh/GB in 2015
HALVING_PERIOD_YEARS = 2.0

# Output defaults
DEFAULT_OUTPUT_FORMAT = "table"
DEFAULT_FIX_OUTPUT_SUFFIX = ".optimized"

# Severity configuration
SEVERITY_COLORS = {
    "high": "red",
    "medium": "yellow",
    "low": "blue",
}

SEVERITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
