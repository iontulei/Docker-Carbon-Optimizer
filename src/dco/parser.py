"""Dockerfile parsing wrapper around dockerfile-parse."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dockerfile_parse import DockerfileParser


@dataclass
class ParsedDockerfile:
    """Structured representation of a parsed Dockerfile."""

    content: str
    instructions: list[dict] = field(default_factory=list)
    baseimage: str = ""
    from_instructions: list[dict] = field(default_factory=list)
    path: Path | None = None


def parse_file(path: str | Path) -> ParsedDockerfile:
    """Parse a Dockerfile from a file path."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dockerfile not found: {path}")
    content = path.read_text(encoding="utf-8")
    return parse_string(content, source_path=path)


def parse_string(content: str, source_path: Path | None = None) -> ParsedDockerfile:
    """Parse a Dockerfile from a string.

    Uses DockerfileParser() with no path arg to avoid filesystem side effects.
    """
    dfp = DockerfileParser()
    dfp.content = content

    instructions = dfp.structure
    from_instructions = [i for i in instructions if i["instruction"] == "FROM"]

    return ParsedDockerfile(
        content=content,
        instructions=instructions,
        baseimage=dfp.baseimage or "",
        from_instructions=from_instructions,
        path=source_path,
    )
