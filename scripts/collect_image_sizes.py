#!/usr/bin/env python3
"""Collect Docker image sizes and tags from Docker Hub API.

Discovers the most-pulled images via Docker Hub's search endpoint
(sorted by pull count), then queries each image's tags for sizes,
slim/alpine variants, and latest pinned versions.

Writes results to src/dco/data/image_sizes.json.

Usage:
    python scripts/collect_image_sizes.py [--top N]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import httpx

# Docker Hub endpoints
SEARCH_DATA_URL = "https://hub.docker.com/search.data"
REPO_INFO_URL = "https://hub.docker.com/v2/repositories/{namespace}/{image}/"
TAGS_URL = "https://hub.docker.com/v2/repositories/{namespace}/{image}/tags/"

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "src" / "dco" / "data" / "image_sizes.json"
)

# Variant suffixes to probe for official images
VARIANT_SUFFIXES = ["-slim", "-alpine"]

# Regex for valid Docker image names: [namespace/]name, lowercase, alphanumeric + hyphens
_IMAGE_NAME_RE = re.compile(r"^[a-z0-9][\w.-]*/[a-z0-9][\w.-]*$")


def discover_top_images(client: httpx.Client, page: int) -> list[str]:
    """Fetch one page of image names from Docker Hub, sorted by pull count.

    Uses the search.data endpoint which returns images ranked by popularity.
    Returns a list of image names like 'library/python', 'grafana/grafana'.
    """
    try:
        resp = client.get(
            SEARCH_DATA_URL,
            params={
                "type": "image",
                "sort": "pull_count",
                "order": "desc",
                "_routes": "root,routes/_layout.search",
                "page": page,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            return []

        data = json.loads(resp.text)

        # Extract image names from the turbo-stream response.
        # Image names appear as strings matching "namespace/image" pattern.
        names = []
        for item in data:
            if isinstance(item, str) and _IMAGE_NAME_RE.match(item):
                names.append(item)
        return names

    except (httpx.RequestError, json.JSONDecodeError):
        return []


def get_repo_info(
    client: httpx.Client, namespace: str, image: str
) -> dict | None:
    """Fetch repository metadata (pull count, star count, etc.)."""
    url = REPO_INFO_URL.format(namespace=namespace, image=image)
    try:
        resp = client.get(url, timeout=15.0)
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.RequestError:
        return None


def get_tags_page(
    client: httpx.Client, namespace: str, image: str, page_size: int = 100
) -> list[dict]:
    """Fetch the first page of tags for an image."""
    url = TAGS_URL.format(namespace=namespace, image=image)
    try:
        resp = client.get(url, params={"page_size": page_size}, timeout=15.0)
        if resp.status_code != 200:
            return []
        return resp.json().get("results", [])
    except httpx.RequestError:
        return []


def extract_size_mb(tag_result: dict) -> float | None:
    """Extract compressed size in MB from a tag result, preferring amd64."""
    full_size = tag_result.get("full_size")
    if full_size and full_size > 0:
        return round(full_size / (1024 * 1024), 1)

    for img in tag_result.get("images", []):
        if img.get("architecture") == "amd64":
            size = img.get("size", 0)
            if size and size > 0:
                return round(size / (1024 * 1024), 1)

    return None


def find_minor_versions(tags: list[dict]) -> dict[str, dict]:
    """Identify minor version tags and their latest pinned patch versions.

    Looks for tags like '3.12', '22', '1.25' (numeric, at most one dot).
    For each, finds the latest patch tag like '3.12.13'.
    """
    tag_info: dict[str, float | None] = {}
    for t in tags:
        name = t.get("name", "")
        if name:
            tag_info[name] = extract_size_mb(t)

    minor_pattern = re.compile(r"^\d+(\.\d+)?$")
    minor_versions: dict[str, dict] = {}

    for tag_name, size in tag_info.items():
        if not minor_pattern.match(tag_name):
            continue
        if size is None:
            continue

        # Find the latest patch tag (e.g., '3.12.13' for '3.12')
        patch_pattern = re.compile(rf"^{re.escape(tag_name)}\.\d+$")
        patch_candidates = [t for t in tag_info if patch_pattern.match(t)]

        pinned = tag_name
        if patch_candidates:
            def patch_num(t: str) -> int:
                parts = t.rsplit(".", 1)
                return int(parts[-1]) if parts[-1].isdigit() else 0

            patch_candidates.sort(key=patch_num, reverse=True)
            pinned = patch_candidates[0]

        minor_versions[tag_name] = {
            "size_mb": size,
            "pinned": pinned,
        }

    return minor_versions


def find_variant_size(tags: list[dict], base_version: str, suffix: str) -> float | None:
    """Find the size of a variant tag like '3.12-slim' or '3.12-alpine'."""
    target = f"{base_version}{suffix}"
    for t in tags:
        if t.get("name") == target:
            return extract_size_mb(t)
    return None


def parse_image_name(full_name: str) -> tuple[str, str]:
    """Split 'library/python' or 'grafana/grafana' into (namespace, image)."""
    if "/" in full_name:
        return full_name.split("/", 1)
    return "library", full_name


def collect_image_data(
    client: httpx.Client, full_name: str, is_official: bool
) -> dict | None:
    """Collect tag/size data for a single image."""
    namespace, image = parse_image_name(full_name)

    tags = get_tags_page(client, namespace, image, page_size=100)
    if not tags:
        return None

    minor_versions = find_minor_versions(tags)
    if not minor_versions:
        return None

    versions_data: dict[str, dict] = {}
    for version, info in minor_versions.items():
        entry: dict = {
            "size_mb": info["size_mb"],
            "pinned": info["pinned"],
        }

        # Only look for slim/alpine variants on official images
        if is_official:
            for suffix in VARIANT_SUFFIXES:
                variant_key = suffix.lstrip("-")  # "slim" or "alpine"
                variant_size = find_variant_size(tags, version, suffix)
                if variant_size is not None:
                    entry[variant_key] = f"{image}:{version}{suffix}"
                    entry[f"{variant_key}_size_mb"] = variant_size
                else:
                    entry[variant_key] = None
                    entry[f"{variant_key}_size_mb"] = None
        else:
            for suffix in VARIANT_SUFFIXES:
                variant_key = suffix.lstrip("-")
                entry[variant_key] = None
                entry[f"{variant_key}_size_mb"] = None

        versions_data[version] = entry

    return versions_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Docker image sizes from Docker Hub.")
    parser.add_argument(
        "--top", type=int, default=50, help="Number of top images to discover (default: 50)"
    )
    args = parser.parse_args()

    print("=== Docker Image Size Collector ===")
    print(f"Discovering top {args.top} images from Docker Hub...\n")

    # Load existing data to preserve minimal_images list
    existing: dict = {}
    if OUTPUT_PATH.exists():
        try:
            existing = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    result: dict = {
        "images": {},
        "minimal_images": existing.get("minimal_images", []),
    }

    with httpx.Client() as client:
        collected = 0
        search_page = 1
        seen: set[str] = set()
        max_pages = 20  # safety limit to avoid infinite loop

        while collected < args.top and search_page <= max_pages:
            # Discover a batch of image names from the next search page
            print(f"  Fetching search page {search_page}...")
            names_batch = discover_top_images(client, search_page)

            if not names_batch:
                print("  No more images found, stopping discovery.")
                break

            # Process each discovered image
            for full_name in names_batch:
                if collected >= args.top:
                    break

                if full_name in seen:
                    continue
                seen.add(full_name)

                namespace, image = parse_image_name(full_name)

                # Skip minimal images - they're already as small as possible
                if any(m in image for m in result["minimal_images"]):
                    print(f"  {full_name} -> skipped (minimal image)")
                    continue
                is_official = namespace == "library"
                tag = "[official]" if is_official else "[community]"

                # Get exact pull count from repo info API
                repo_info = get_repo_info(client, namespace, image)
                pull_count = repo_info.get("pull_count", 0) if repo_info else 0

                print(f"  {full_name} {tag} ({pull_count:,} pulls)")

                data = collect_image_data(client, full_name, is_official)
                if data:
                    result["images"][full_name] = {
                        "is_official": is_official,
                        "pull_count": pull_count,
                        "versions": data,
                    }
                    collected += 1
                    print(f"    -> {len(data)} version(s) collected ({collected}/{args.top})")
                else:
                    print(f"    -> skipped (no parseable version tags)")

                # Be polite to the API
                time.sleep(0.3)

            search_page += 1

    # Write output
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    total_versions = sum(
        len(img["versions"]) for img in result["images"].values()
    )
    print(f"\nDone! Wrote {len(result['images'])} images ({total_versions} versions) to:")
    print(f"  {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
