"""Tests for dco.carbon.estimator - CarbonEstimator and convenience helpers."""

from __future__ import annotations

import pytest

from dco.carbon.estimator import (
    CarbonEstimate,
    CarbonEstimator,
    estimate_co2_grams,
    get_grid_intensity,
)


class TestNetworkKwhPerGb:
    def test_baseline_year_returns_raw_value(self):
        # 2015 is the Aslan baseline → 0.06 kWh/GB
        assert CarbonEstimator._network_kwh_per_gb(2015) == pytest.approx(0.06)

    def test_one_halving_period(self):
        # 2 years later → 0.03
        assert CarbonEstimator._network_kwh_per_gb(2017) == pytest.approx(0.03)

    def test_two_halving_periods(self):
        # 4 years later → 0.015
        assert CarbonEstimator._network_kwh_per_gb(2019) == pytest.approx(0.015)

    def test_value_decreases_over_time(self):
        v2020 = CarbonEstimator._network_kwh_per_gb(2020)
        v2025 = CarbonEstimator._network_kwh_per_gb(2025)
        assert v2025 < v2020


class TestCarbonEstimator:
    def test_estimate_returns_dataclass(self):
        est = CarbonEstimator(pulls_per_month=1000, region="world")
        result = est.estimate(1.0)
        assert isinstance(result, CarbonEstimate)
        assert result.co2_kg_per_month > 0

    def test_region_affects_result(self):
        est_fr = CarbonEstimator(pulls_per_month=1000, region="fr")
        est_cn = CarbonEstimator(pulls_per_month=1000, region="cn")
        r_fr = est_fr.estimate(1.0)
        r_cn = est_cn.estimate(1.0)
        # China grid (581) >> France grid (22)
        assert r_cn.co2_kg_per_month > r_fr.co2_kg_per_month * 10

    def test_unknown_region_uses_world_default(self):
        est_unknown = CarbonEstimator(region="zz_nonexistent")
        r_u = est_unknown.estimate(1.0)
        assert r_u.co2_kg_per_month > 0

    def test_zero_size_returns_zero(self):
        est = CarbonEstimator()
        result = est.estimate(0.0)
        assert result.co2_kg_per_month == 0.0


class TestEstimateCo2Grams:
    def test_returns_grams_not_kg(self):
        grams = estimate_co2_grams(1000.0, pulls_per_month=1000, region="world")
        # For 1 GB, 1000 pulls, the result should be in grams (> 0 but reasonable)
        assert grams > 0

    def test_consistent_with_estimator(self):
        grams = estimate_co2_grams(500.0, pulls_per_month=2000, region="eu")
        est = CarbonEstimator(pulls_per_month=2000, region="eu")
        result = est.estimate(500.0 / 1000)
        assert grams == pytest.approx(result.co2_kg_per_month * 1000)


class TestGridIntensityData:
    def test_loads_from_json(self):
        grid = get_grid_intensity()
        assert len(grid) >= 16

    def test_known_regions_present(self):
        grid = get_grid_intensity()
        for region in ("world", "us", "eu", "uk", "fr", "de", "cn"):
            assert region in grid
            assert grid[region] > 0
