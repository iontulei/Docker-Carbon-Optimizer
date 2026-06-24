"""CodeCarbon wrapper for measuring Docker image build energy and CO2."""

from __future__ import annotations

import importlib.util
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_CODECARBON_AVAILABLE = importlib.util.find_spec("codecarbon") is not None


@dataclass
class BuildMeasurement:
    """Energy and CO2 measured during a single Docker build."""

    energy_kwh: float
    co2_kg: float
    duration_seconds: float
    backend: str  # "codecarbon" or "unavailable"


class CodeCarbonUnavailableError(RuntimeError):
    """Raised when codecarbon is not installed and measurement is attempted."""


class BuildEnergyTracker:
    """Wraps a Docker build (or any callable) with CodeCarbon measurement.

    Usage - wrap a callable::

        tracker = BuildEnergyTracker(project_name="my-image")
        result = tracker.measure(lambda: subprocess.run(["docker", "build", "."]))

    Usage - wrap a shell command directly::

        measurement = tracker.measure_command(
            ["docker", "build", "-t", "myapp:latest", "."],
            cwd="/path/to/project",
        )

    Install the optional dependency to enable::

        pip install dockerfile-carbon-optimizer[energy]
    """

    def __init__(
        self,
        project_name: str = "dco-build",
        output_dir: Path | str | None = None,
        log_level: str = "error",
    ) -> None:
        self.project_name = project_name
        self.output_dir = Path(output_dir) if output_dir else None
        self.log_level = log_level

    def _make_tracker(self) -> Any:
        from codecarbon import EmissionsTracker  # type: ignore[import-not-found]  # noqa: PLC0415

        kwargs: dict = {
            "project_name": self.project_name,
            "logging_logger": None,
            "log_level": self.log_level,
            "save_to_file": self.output_dir is not None,
        }
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            kwargs["output_dir"] = str(self.output_dir)
        return EmissionsTracker(**kwargs)

    def measure(self, fn: Callable[[], object]) -> BuildMeasurement:
        """Run *fn* under CodeCarbon and return the measurement.

        Args:
            fn: Zero-argument callable wrapping the work to measure.

        Returns:
            BuildMeasurement with energy_kwh, co2_kg, and duration_seconds.

        Raises:
            CodeCarbonUnavailableError: if codecarbon is not installed.
        """
        if not _CODECARBON_AVAILABLE:
            raise CodeCarbonUnavailableError(
                "codecarbon is not installed. "
                "Run: pip install dockerfile-carbon-optimizer[energy]"
            )

        import time

        tracker = self._make_tracker()
        tracker.start()
        t0 = time.perf_counter()
        try:
            fn()
        finally:
            emissions_kg = tracker.stop()  # returns kg CO2
            duration = time.perf_counter() - t0

        # EmissionsTracker.stop() returns kg CO2; energy is in tracker.final_emissions_data
        energy_kwh: float = 0.0
        if hasattr(tracker, "final_emissions_data") and tracker.final_emissions_data is not None:
            energy_kwh = float(getattr(tracker.final_emissions_data, "energy_consumed", 0.0))

        return BuildMeasurement(
            energy_kwh=energy_kwh,
            co2_kg=float(emissions_kg) if emissions_kg is not None else 0.0,
            duration_seconds=duration,
            backend="codecarbon",
        )

    def measure_command(
        self,
        cmd: list[str],
        cwd: Path | str | None = None,
        check: bool = True,
    ) -> BuildMeasurement:
        """Run a shell command under CodeCarbon measurement.

        Args:
            cmd:   Command and arguments, e.g. ``["docker", "build", "."]``.
            cwd:   Working directory for the subprocess (default: current dir).
            check: If True, raise CalledProcessError on non-zero exit.

        Returns:
            BuildMeasurement with energy and CO2 from the build.
        """

        def _run() -> None:
            subprocess.run(cmd, cwd=cwd, check=check)

        return self.measure(_run)

    @staticmethod
    def is_available() -> bool:
        """Return True if codecarbon is installed and measurement is possible."""
        return _CODECARBON_AVAILABLE
