"""DCO006: Detect unpinned base image tags."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dco.data import get_image_data
from dco.rules import Finding, FixAction, register
from dco.rules._utils import parse_from_value as _parse_from_value

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile


def _is_pinned(tag: str) -> bool:
    """Check if a tag is pinned to at least minor version precision.

    Pinned (returns True):
        '3.12'          - minor level
        '3.12.13'       - patch level
        '3.12-slim'     - minor + variant
        '22.04'         - Ubuntu-style
        '21.0.10_7'     - Eclipse Temurin style

    Unpinned (returns False):
        ''              - no tag (defaults to :latest)
        'latest'        - explicit latest
        '3'             - major only
    """
    if not tag:
        return False
    if tag == "latest":
        return False

    # If it contains a digest, it's fully pinned
    if "@" in tag:
        return True

    # Strip variant suffix for version checking (e.g., '3.12-slim' -> '3.12')
    version_part = tag.split("-")[0]

    # Major-only: single number like '3', '8', '22'
    if version_part.isdigit():
        return False

    # Has at least one dot -> minor precision or better
    if "." in version_part:
        return True

    # Non-numeric tags like 'bookworm', 'bullseye' are codenames - considered pinned
    # (they map to a specific release)
    return True


def _find_pinned_tag(image: str, data: dict, current_tag: str = "") -> str | None:
    """Look up the recommended pinned tag for an image in image_sizes.json.

    When *current_tag* carries a major version (e.g. "22", "22-alpine"),
    the lookup prefers a pinned version within the same major to avoid
    breaking upgrades (e.g. node 22 -> 22.15.0, not 25.8.2).
    """
    images = data.get("images", {})

    # Find the image entry
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
        return None

    versions = image_entry.get("versions", {})
    if not versions:
        return None

    def version_sort_key(v: str) -> tuple:
        parts = v.split(".")
        return tuple(int(p) for p in parts if p.isdigit())

    # Extract major version from current tag (e.g. "22-alpine" -> "22")
    major = ""
    if current_tag:
        major = current_tag.split("-")[0].split(".")[0]

    # Prefer a version matching the same major
    if major and major.isdigit():
        same_major = [v for v in versions if v.split(".")[0] == major]
        if same_major:
            same_major.sort(key=version_sort_key, reverse=True)
            best = same_major[0]
            return versions[best].get("pinned", best)

    # Fallback: highest version overall
    sorted_versions = sorted(versions.keys(), key=version_sort_key, reverse=True)
    best_version = sorted_versions[0]
    return versions[best_version].get("pinned", best_version)


@register
class PinningRule:
    rule_id = "DCO006"
    name = "Unpinned base image tag"
    description = "Detect base images using unpinned tags like :latest or no tag."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        findings: list[Finding] = []
        data = get_image_data()

        for instr in parsed_dockerfile.from_instructions:
            value = instr.get("value", "")
            if not value:
                continue

            image, tag = _parse_from_value(value)

            # Skip scratch - it has no tags
            if image == "scratch":
                continue

            # Skip if already pinned
            if _is_pinned(tag):
                continue

            start_line = instr["startline"]
            end_line = instr["endline"]

            # Try to find a pinned tag to recommend
            pinned_tag = _find_pinned_tag(image, data, current_tag=tag)

            if tag:
                issue_desc = f"Using {image}:{tag} which is not pinned to a specific version."
            else:
                issue_desc = f"Using {image} without a tag (defaults to :latest)."

            if pinned_tag:
                # Preserve AS alias
                parts = value.split()
                as_suffix = ""
                if len(parts) >= 3 and parts[1].upper() == "AS":
                    as_suffix = f" AS {parts[2]}"

                # Preserve variant suffix (-alpine, -slim, -bookworm, etc.)
                variant_suffix = ""
                if tag:
                    dash_idx = tag.find("-")
                    if dash_idx >= 0:
                        variant_suffix = tag[dash_idx:]

                new_from = f"FROM {image}:{pinned_tag}{variant_suffix}{as_suffix}\n"

                findings.append(
                    Finding(
                        rule_id="DCO006",
                        severity="low",
                        line=start_line,
                        issue=issue_desc,
                        fix=f"Pin to {image}:{pinned_tag}{variant_suffix}",
                        size_saved_mb=0.0,
                        original_size_mb=0.0,
                        auto_fixable=True,
                        fix_action=FixAction(
                            action_type="pin_tag",
                            target_lines=(start_line, end_line),
                            new_content=new_from,
                        ),
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id="DCO006",
                        severity="low",
                        line=start_line,
                        issue=issue_desc,
                        fix="Pin to a specific version tag for reproducible builds.",
                        size_saved_mb=0.0,
                        original_size_mb=0.0,
                        auto_fixable=False,
                    )
                )

        return findings
