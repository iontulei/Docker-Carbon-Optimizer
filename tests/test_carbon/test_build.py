"""Tests for dco.carbon.build - BuildEnergyTracker."""

from __future__ import annotations

import pytest

from dco.carbon.build import (
    BuildEnergyTracker,
    CodeCarbonUnavailableError,
)


def test_is_available_returns_bool():
    result = BuildEnergyTracker.is_available()
    assert isinstance(result, bool)


def test_unavailable_raises_error_when_codecarbon_missing():
    if BuildEnergyTracker.is_available():
        pytest.skip("codecarbon is installed - cannot test unavailable path")
    tracker = BuildEnergyTracker()
    with pytest.raises(CodeCarbonUnavailableError):
        tracker.measure(lambda: None)


def test_measure_command_delegates_to_measure():
    """measure_command wraps a subprocess call through measure()."""
    if BuildEnergyTracker.is_available():
        pytest.skip("codecarbon is installed - cannot test unavailable path")
    tracker = BuildEnergyTracker()
    with pytest.raises(CodeCarbonUnavailableError):
        tracker.measure_command(["echo", "hello"])
