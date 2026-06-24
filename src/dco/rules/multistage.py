"""DCO005: Detect missing multi-stage builds for compiled languages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dco.data import get_image_data
from dco.rules import Finding, register

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile

# Compressed size of a minimal runtime image in MB.
# Alpine is ~3-5 MB, gcr.io/distroless/base is ~2-3 MB.
# We use 5 MB as a conservative estimate.
_RUNTIME_BASELINE_MB = 5.0

# Base-image names (after stripping registry prefix and tag) that indicate a
# compiled language where multi-stage builds are strongly recommended.
_COMPILED_IMAGES: set[str] = {
    "golang",
    "rust",
    "maven",
    "openjdk",
    "gradle",
    "eclipse-temurin",
}

# Substrings in RUN values that confirm the image is actually used for compilation.
_COMPILE_COMMANDS: list[str] = [
    "go build",
    "cargo build",
    "mvn package",
    "mvn install",
    "gradle build",
    "gradle assemble",
    "javac",
]


def _extract_image_name(baseimage: str) -> str:
    """Strip registry prefix and tag to get the bare image name.

    Examples:
        "golang:1.21"                   -> "golang"
        "docker.io/library/rust:latest" -> "rust"
        "gcr.io/distroless/base"        -> "base"
    """
    # Remove tag / digest.
    name = baseimage.split("@")[0].split(":")[0]
    # Take the last path segment (handles registry/org/image).
    return name.rsplit("/", 1)[-1]


def _lookup_base_image_size(image_name: str, tag: str) -> float | None:
    """Look up the compressed size of *image_name* in image_sizes.json."""
    data = get_image_data()
    images = data.get("images", {})

    # Find the image entry.
    image_entry = None
    if f"library/{image_name}" in images:
        image_entry = images[f"library/{image_name}"]
    else:
        for key, val in images.items():
            _, name = key.split("/", 1) if "/" in key else ("", key)
            if name == image_name:
                image_entry = val
                break

    if image_entry is None:
        return None

    versions = image_entry.get("versions", {})
    if not versions:
        return None

    # Try exact tag match, then first available version.
    if tag in versions:
        return versions[tag].get("size_mb")

    # Fallback: use the first (highest) version.
    first = next(iter(versions.values()), {})
    return first.get("size_mb")


@register
class MultistageRule:
    rule_id = "DCO005"
    name = "Missing Multi-stage Build"
    description = "Detects compiled-language images without multi-stage builds."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        # Already multi-stage - nothing to report.
        if len(parsed_dockerfile.from_instructions) >= 2:
            return []

        image_name = _extract_image_name(parsed_dockerfile.baseimage)
        if image_name not in _COMPILED_IMAGES:
            return []

        # Confirm there's an actual compile command.
        has_compile = any(
            any(cmd in instr["value"] for cmd in _COMPILE_COMMANDS)
            for instr in parsed_dockerfile.instructions
            if instr["instruction"] == "RUN"
        )
        if not has_compile:
            return []

        # Estimate savings: base image size minus a minimal runtime baseline.
        tag = parsed_dockerfile.baseimage.split(":")[-1] if ":" in parsed_dockerfile.baseimage else ""
        base_size = _lookup_base_image_size(image_name, tag)
        if base_size is not None:
            size_saved = max(base_size - _RUNTIME_BASELINE_MB, 0.0)
        else:
            size_saved = 0.0

        from_line = parsed_dockerfile.from_instructions[0]["startline"]

        if size_saved > 0:
            size_note = f" (~{size_saved:.0f} MB)"
        else:
            size_note = ""

        return [
            Finding(
                rule_id="DCO005",
                severity="medium",
                line=from_line,
                issue=(
                    f"Single-stage build with compiled-language image "
                    f"'{parsed_dockerfile.baseimage}'. Build tools and "
                    f"source code remain in the final image{size_note}."
                ),
                fix=(
                    f"Use a multi-stage build: compile in a builder "
                    f"stage (FROM {parsed_dockerfile.baseimage} AS "
                    f"builder), then copy the binary into a minimal "
                    f"runtime image (e.g. gcr.io/distroless/base)."
                ),
                size_saved_mb=size_saved,
                original_size_mb=base_size if base_size is not None else 0.0,
                auto_fixable=False,
                fix_action=None,
            )
        ]
