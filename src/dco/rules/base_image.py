"""DCO001: Detect oversized base images and suggest slim/alpine alternatives."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dco.data import get_image_data
from dco.rules import Finding, FixAction, register
from dco.rules._utils import parse_from_value as _parse_from_value

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile


def _is_already_minimal(image: str, tag: str, minimal_images: list[str]) -> bool:
    """Check if the image is already a minimal variant."""
    # Check if it's a known minimal base image
    for m in minimal_images:
        if m in image:
            return True

    # Check if the tag already uses a slim/alpine variant
    if tag and any(suffix in tag for suffix in ("-slim", "-alpine", "slim", "alpine")):
        return True

    return False


def _lookup_image(image: str, tag: str, data: dict) -> tuple[dict | None, str | None]:
    """Look up an image in image_sizes.json data.

    Returns (version_data, matched_key) or (None, None) if not found.
    The lookup tries both 'library/{image}' and other namespace formats.
    """
    images = data.get("images", {})

    # Find the image entry - try 'library/{image}' first, then scan all keys
    image_entry = None
    if f"library/{image}" in images:
        image_entry = images[f"library/{image}"]
    else:
        for key, value in images.items():
            _, img_name = key.split("/", 1) if "/" in key else ("", key)
            if img_name == image:
                image_entry = value
                break

    if image_entry is None:
        return None, None

    versions = image_entry.get("versions", {})
    if not versions:
        return None, None

    # Try exact version match
    if tag in versions:
        return versions[tag], tag

    # Try matching major-only tag to highest minor (e.g., '3' -> '3.12')
    if tag and tag.isdigit():
        candidates = [v for v in versions if v.startswith(f"{tag}.")]
        if candidates:
            # Sort by minor version descending
            def minor_num(v: str) -> float:
                parts = v.split(".")
                return float(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

            candidates.sort(key=minor_num, reverse=True)
            best = candidates[0]
            return versions[best], best

    return None, None


@register
class BaseImageRule:
    rule_id = "DCO001"
    name = "Oversized base image"
    description = "Detect base images that have smaller slim or alpine alternatives."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        findings: list[Finding] = []
        data = get_image_data()
        minimal_images = data.get("minimal_images", [])

        for instr in parsed_dockerfile.from_instructions:
            value = instr.get("value", "")
            if not value:
                continue

            image, tag = _parse_from_value(value)

            # Skip if already minimal
            if _is_already_minimal(image, tag, minimal_images):
                continue

            # Skip if no tag or tag is 'latest' - that's DCO006's job
            # But we still check if the base image itself has a slim variant
            lookup_tag = tag if tag and tag != "latest" else ""

            # If no usable tag, try to find any version to check for slim
            if not lookup_tag:
                # Check if the image has any versions at all
                images = data.get("images", {})
                image_entry = None
                if f"library/{image}" in images:
                    image_entry = images[f"library/{image}"]
                else:
                    for key, val in images.items():
                        _, img_name = key.split("/", 1) if "/" in key else ("", key)
                        if img_name == image:
                            image_entry = val
                            break

                if image_entry is None:
                    continue

                # Use the highest version available
                versions = image_entry.get("versions", {})
                if not versions:
                    continue

                sorted_versions = sorted(versions.keys(), reverse=True)
                lookup_tag = sorted_versions[0]

            version_data, matched_version = _lookup_image(image, lookup_tag, data)
            if version_data is None:
                continue

            current_size = version_data.get("size_mb", 0)

            # Prefer slim, fall back to alpine
            suggested_variant = None
            suggested_size = None

            if version_data.get("slim") and version_data.get("slim_size_mb"):
                suggested_variant = version_data["slim"]
                suggested_size = version_data["slim_size_mb"]
            elif version_data.get("alpine") and version_data.get("alpine_size_mb"):
                suggested_variant = version_data["alpine"]
                suggested_size = version_data["alpine_size_mb"]

            if suggested_variant is None or suggested_size is None:
                continue

            size_saved = current_size - suggested_size
            if size_saved <= 0:
                continue

            # Build the new FROM line
            # Preserve AS alias if present
            parts = value.split()
            as_suffix = ""
            if len(parts) >= 3 and parts[1].upper() == "AS":
                as_suffix = f" AS {parts[2]}"

            new_from = f"FROM {suggested_variant}{as_suffix}\n"

            start_line = instr["startline"]
            end_line = instr["endline"]

            findings.append(
                Finding(
                    rule_id="DCO001",
                    severity="high",
                    line=start_line,
                    issue=(
                        f"Using {image}:{tag or 'latest'} "
                        f"({current_size:.0f} MB). "
                        f"Consider {suggested_variant} "
                        f"({suggested_size:.0f} MB, "
                        f"saves ~{size_saved:.0f} MB)."
                    ),
                    fix=(
                        f"Switch to {suggested_variant}. "
                        f"Slim images remove build tools (gcc, "
                        f"dev headers). Verify your app has no "
                        f"native dependencies before switching. "
                        f"Use --force to auto-fix."
                    ),
                    size_saved_mb=size_saved,
                    original_size_mb=current_size,
                    auto_fixable=False,
                    fix_action=FixAction(
                        action_type="replace_from",
                        target_lines=(start_line, end_line),
                        new_content=new_from,
                    ),
                )
            )

        return findings
