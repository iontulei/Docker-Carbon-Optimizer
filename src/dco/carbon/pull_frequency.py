"""Docker Hub pull frequency estimator.

Fetches cumulative pull_count and registration date from the Docker Hub API,
then derives a lifetime-average pulls-per-month figure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from dco.config import DEFAULT_PULLS_PER_MONTH

_DOCKER_HUB_API = "https://hub.docker.com/v2/repositories/{namespace}/{image}/"
_OFFICIAL_NAMESPACE = "library"  # Docker Hub namespace for official images


@dataclass
class PullFrequency:
    image: str
    namespace: str
    total_pulls: int
    months_active: int
    pulls_per_month: float


class DockerHubError(Exception):
    """Raised when the Docker Hub API returns an unexpected response."""


def _parse_image_ref(image_ref: str) -> tuple[str, str]:
    """Split 'namespace/image' or 'image' into (namespace, image).

    Official images (e.g. 'python', 'nginx') use the 'library' namespace.
    """
    if "/" in image_ref:
        namespace, image = image_ref.split("/", 1)
    else:
        namespace, image = _OFFICIAL_NAMESPACE, image_ref
    # Strip any tag (python:3.12-slim → python)
    image = image.split(":")[0]
    return namespace, image


def _months_since(registration_date: str) -> int:
    """Return whole months elapsed since an ISO 8601 date string."""
    registered = datetime.fromisoformat(registration_date.replace("Z", "+00:00"))
    now = datetime.now(tz=timezone.utc)
    months = (now.year - registered.year) * 12 + (now.month - registered.month)
    return max(months, 1)  # floor at 1 to avoid division by zero for brand-new images


def fetch_pull_frequency(
    image_ref: str,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> PullFrequency:
    """Query Docker Hub for pull statistics and return pulls-per-month.

    Args:
        image_ref: Image reference, e.g. ``"python"``, ``"python:3.12-slim"``,
                   or ``"myorg/myimage"``.
        timeout:   HTTP request timeout in seconds.
        client:    Optional pre-configured httpx.Client (useful for testing).

    Returns:
        PullFrequency with total pulls, months active, and derived rate.

    Raises:
        DockerHubError: on HTTP errors or unexpected API responses.
    """
    namespace, image = _parse_image_ref(image_ref)
    url = _DOCKER_HUB_API.format(namespace=namespace, image=image)

    def _get(c: httpx.Client) -> dict:
        response = c.get(url, timeout=timeout)
        if response.status_code == 404:
            raise DockerHubError(f"Image not found on Docker Hub: {namespace}/{image}")
        if response.status_code != 200:
            raise DockerHubError(
                f"Docker Hub API returned {response.status_code} for {namespace}/{image}"
            )
        return response.json()

    if client is not None:
        data = _get(client)
    else:
        with httpx.Client() as c:
            data = _get(c)

    try:
        total_pulls: int = int(data["pull_count"])
        registration_date: str = data["date_registered"]
    except (KeyError, TypeError, ValueError) as exc:
        raise DockerHubError(f"Unexpected Docker Hub API response: {exc}") from exc

    months = _months_since(registration_date)
    pulls_per_month = total_pulls / months

    return PullFrequency(
        image=image,
        namespace=namespace,
        total_pulls=total_pulls,
        months_active=months,
        pulls_per_month=pulls_per_month,
    )


def get_pulls_per_month(
    image_ref: str,
    fallback: float = DEFAULT_PULLS_PER_MONTH,
    timeout: float = 10.0,
    client: httpx.Client | None = None,
) -> float:
    """Return pulls-per-month for *image_ref*, falling back to *fallback* on any error.

    This is the convenience entry point for use in the carbon model - it never
    raises, so a transient network failure or private registry doesn't break the
    analysis.
    """
    try:
        return fetch_pull_frequency(image_ref, timeout=timeout, client=client).pulls_per_month
    except Exception:
        return fallback
