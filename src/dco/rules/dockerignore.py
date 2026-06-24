"""DCO004: Detect missing .dockerignore file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dco.fixer_templates import detect_language, get_dockerignore_template
from dco.rules import Finding, FixAction, register

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile

# Directories commonly excluded by .dockerignore. If any of these exist
# and no .dockerignore is present, the full directory is sent to the
# Docker daemon unnecessarily.
_EXCLUDABLE_DIRS = [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "target",
    ".gradle",
    "vendor",
    ".next",
]


def _scan_excludable_size(directory: Path) -> float:
    """Return total size in MB of excludable directories found in *directory*."""
    total_bytes = 0
    for name in _EXCLUDABLE_DIRS:
        path = directory / name
        if not path.is_dir():
            continue
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total_bytes += f.stat().st_size
        except OSError:
            continue
    return total_bytes / (1024 * 1024)


@register
class DockerignoreRule:
    rule_id = "DCO004"
    name = "Missing .dockerignore"
    description = "Detects when no .dockerignore file exists in the build context."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        dockerfile_dir: Path | None = context.get("dockerfile_dir")
        if dockerfile_dir is None:
            return []

        dockerignore_path = dockerfile_dir / ".dockerignore"
        if dockerignore_path.exists():
            return []

        language = detect_language(dockerfile_dir)
        template = get_dockerignore_template(language)

        size_mb = _scan_excludable_size(dockerfile_dir)

        if size_mb > 0:
            issue = (
                f"No .dockerignore file found. ~{size_mb:.1f} MB of "
                f"excludable files (.git, node_modules, .venv, etc.) "
                f"are sent to the Docker daemon."
            )
        else:
            issue = (
                "No .dockerignore file found. The entire build context "
                "is sent to the Docker daemon."
            )

        return [
            Finding(
                rule_id="DCO004",
                severity="low",
                line=0,
                issue=issue,
                fix=(
                    "Create a .dockerignore file to exclude unnecessary "
                    "files from the build context."
                ),
                size_saved_mb=size_mb,
                original_size_mb=size_mb,
                auto_fixable=True,
                fix_action=FixAction(
                    action_type="generate_dockerignore",
                    target_lines=(-1, -1),
                    new_content=template,
                ),
            )
        ]
