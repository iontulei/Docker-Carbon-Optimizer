"""Tests for dco.carbon.pull_frequency."""

from __future__ import annotations

import httpx
import pytest
import respx

from dco.carbon.pull_frequency import (
    DockerHubError,
    PullFrequency,
    _months_since,
    _parse_image_ref,
    fetch_pull_frequency,
    get_pulls_per_month,
)
from dco.config import DEFAULT_PULLS_PER_MONTH

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HUB_BASE = "https://hub.docker.com/v2/repositories"


def _hub_url(namespace: str, image: str) -> str:
    return f"{_HUB_BASE}/{namespace}/{image}/"


def _repo_payload(
    pull_count: int = 1_200_000,
    date_registered: str = "2020-01-01T00:00:00Z",
) -> dict:
    return {"pull_count": pull_count, "date_registered": date_registered}


# ---------------------------------------------------------------------------
# _parse_image_ref
# ---------------------------------------------------------------------------

class TestParseImageRef:
    def test_official_image_gets_library_namespace(self):
        assert _parse_image_ref("python") == ("library", "python")

    def test_namespaced_image(self):
        assert _parse_image_ref("myorg/myimage") == ("myorg", "myimage")

    def test_tag_is_stripped(self):
        assert _parse_image_ref("python:3.12-slim") == ("library", "python")

    def test_namespaced_image_tag_is_stripped(self):
        assert _parse_image_ref("myorg/myimage:latest") == ("myorg", "myimage")


# ---------------------------------------------------------------------------
# _months_since
# ---------------------------------------------------------------------------

class TestMonthsSince:
    def test_old_date_returns_many_months(self):
        months = _months_since("2020-01-01T00:00:00Z")
        assert months > 12

    def test_very_recent_date_floors_at_one(self):
        # A date in the far future should still floor at 1
        months = _months_since("2099-12-31T00:00:00Z")
        assert months == 1

    def test_same_month_floors_at_one(self):
        from datetime import datetime, timezone
        now = datetime.now(tz=timezone.utc)
        date_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _months_since(date_str) == 1


# ---------------------------------------------------------------------------
# fetch_pull_frequency
# ---------------------------------------------------------------------------

class TestFetchPullFrequency:
    @respx.mock
    def test_official_image_success(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(200, json=_repo_payload(1_200_000, "2020-01-01T00:00:00Z"))
        )
        result = fetch_pull_frequency("python")

        assert isinstance(result, PullFrequency)
        assert result.namespace == "library"
        assert result.image == "python"
        assert result.total_pulls == 1_200_000
        assert result.months_active >= 1
        assert result.pulls_per_month == result.total_pulls / result.months_active

    @respx.mock
    def test_namespaced_image_success(self):
        respx.get(_hub_url("myorg", "myimage")).mock(
            return_value=httpx.Response(200, json=_repo_payload(50_000, "2022-06-01T00:00:00Z"))
        )
        result = fetch_pull_frequency("myorg/myimage")

        assert result.namespace == "myorg"
        assert result.image == "myimage"
        assert result.total_pulls == 50_000

    @respx.mock
    def test_tag_is_ignored(self):
        respx.get(_hub_url("library", "nginx")).mock(
            return_value=httpx.Response(200, json=_repo_payload())
        )
        result = fetch_pull_frequency("nginx:alpine")
        assert result.image == "nginx"

    @respx.mock
    def test_404_raises_docker_hub_error(self):
        respx.get(_hub_url("library", "doesnotexist")).mock(
            return_value=httpx.Response(404)
        )
        with pytest.raises(DockerHubError, match="not found"):
            fetch_pull_frequency("doesnotexist")

    @respx.mock
    def test_non_200_raises_docker_hub_error(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(DockerHubError, match="500"):
            fetch_pull_frequency("python")

    @respx.mock
    def test_missing_pull_count_raises_docker_hub_error(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(200, json={"date_registered": "2020-01-01T00:00:00Z"})
        )
        with pytest.raises(DockerHubError, match="Unexpected"):
            fetch_pull_frequency("python")

    @respx.mock
    def test_missing_date_registered_raises_docker_hub_error(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(200, json={"pull_count": 100})
        )
        with pytest.raises(DockerHubError, match="Unexpected"):
            fetch_pull_frequency("python")

    @respx.mock
    def test_pulls_per_month_calculation(self):
        # Use a fixed registration date far enough in the past to get stable months count
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(200, json=_repo_payload(1_200, "2020-01-01T00:00:00Z"))
        )
        result = fetch_pull_frequency("python")
        assert result.pulls_per_month == pytest.approx(1_200 / result.months_active)

    def test_injectable_client(self):
        """Passing a custom httpx.Client is used instead of creating a new one."""
        payload = _repo_payload(999, "2021-03-01T00:00:00Z")
        with respx.mock() as mock:
            mock.get(_hub_url("library", "redis")).mock(
                return_value=httpx.Response(200, json=payload)
            )
            with httpx.Client() as client:
                result = fetch_pull_frequency("redis", client=client)
        assert result.total_pulls == 999


# ---------------------------------------------------------------------------
# get_pulls_per_month
# ---------------------------------------------------------------------------

class TestGetPullsPerMonth:
    @respx.mock
    def test_returns_rate_on_success(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(200, json=_repo_payload(600_000, "2020-01-01T00:00:00Z"))
        )
        rate = get_pulls_per_month("python")
        assert rate > 0

    @respx.mock
    def test_falls_back_on_404(self):
        respx.get(_hub_url("library", "ghost")).mock(
            return_value=httpx.Response(404)
        )
        assert get_pulls_per_month("ghost") == DEFAULT_PULLS_PER_MONTH

    @respx.mock
    def test_falls_back_on_network_error(self):
        respx.get(_hub_url("library", "python")).mock(side_effect=httpx.ConnectError("refused"))
        assert get_pulls_per_month("python") == DEFAULT_PULLS_PER_MONTH

    @respx.mock
    def test_custom_fallback_value(self):
        respx.get(_hub_url("library", "python")).mock(
            return_value=httpx.Response(500)
        )
        assert get_pulls_per_month("python", fallback=42.0) == 42.0

