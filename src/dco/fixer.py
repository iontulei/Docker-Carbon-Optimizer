"""Auto-fix engine for applying FixActions to Dockerfiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dockerfile_parse import DockerfileParser

from dco.rules import Finding


@dataclass
class FixResult:
    """Result of applying fixes to a Dockerfile."""

    original_content: str
    fixed_content: str
    applied_fixes: list[Finding] = field(default_factory=list)
    skipped_fixes: list[Finding] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.original_content != self.fixed_content


def apply_fixes(
    content: str,
    findings: list[Finding],
    rules_filter: set[str] | None = None,
    force: bool = False,
) -> FixResult:
    """Apply auto-fixes to Dockerfile content.

    Sorts FixActions by line number descending (bottom-to-top) so that
    earlier fixes don't shift line numbers for later ones.

    When *force* is True, also apply fixes for findings that have a
    ``fix_action`` but ``auto_fixable=False`` (e.g. DCO001 base image swap).
    """
    # Separate fixable from non-fixable findings
    fixable = []
    skipped = []
    for f in findings:
        if (
            f.fix_action is not None
            and (f.auto_fixable or force)
            and (rules_filter is None or f.rule_id in rules_filter)
        ):
            fixable.append(f)
        else:
            skipped.append(f)

    if not fixable:
        return FixResult(
            original_content=content,
            fixed_content=content,
            skipped_fixes=skipped,
        )

    # Sort by start line descending (bottom-to-top)
    fixable.sort(key=lambda f: f.fix_action.target_lines[0], reverse=True)

    lines = content.splitlines(True)
    applied = []
    modified_ranges: list[tuple[int, int]] = []

    for finding in fixable:
        action = finding.fix_action
        start, end = action.target_lines

        # External-file actions (e.g. generate_dockerignore) cannot be applied
        # as line replacements.  Keep them for apply_external_fixes().
        if start < 0:
            skipped.append(finding)
            continue

        # Check for overlap with already-applied fixes
        if _overlaps(start, end, modified_ranges):
            skipped.append(finding)
            continue

        # Apply the replacement
        new_lines = action.new_content.splitlines(True)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"

        lines[start : end + 1] = new_lines
        applied.append(finding)
        modified_ranges.append((start, end))

    fixed_content = "".join(lines)

    return FixResult(
        original_content=content,
        fixed_content=fixed_content,
        applied_fixes=applied,
        skipped_fixes=skipped,
    )


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """Check if a line range overlaps with any already-modified ranges."""
    for r_start, r_end in ranges:
        if start <= r_end and end >= r_start:
            return True
    return False


def validate_fix(fixed_content: str) -> bool:
    """Verify that fixed content is syntactically valid by re-parsing."""
    try:
        dfp = DockerfileParser()
        dfp.content = fixed_content
        # If it parses without error and has at least a FROM, it's valid
        return any(i["instruction"] == "FROM" for i in dfp.structure)
    except Exception:
        return False


def write_fix(fix_result: FixResult, output_path: Path) -> None:
    """Write the fixed Dockerfile content to disk."""
    output_path.write_text(fix_result.fixed_content, encoding="utf-8")


def apply_external_fixes(findings: list[Finding], dockerfile_dir: Path) -> list[Path]:
    """Handle fix actions that produce files outside the Dockerfile itself.

    Currently supports ``generate_dockerignore`` which writes a ``.dockerignore``
    file into *dockerfile_dir*.  Returns paths of files written.
    """
    written: list[Path] = []
    for f in findings:
        if not f.auto_fixable or f.fix_action is None:
            continue
        if f.fix_action.action_type == "generate_dockerignore":
            dest = dockerfile_dir / ".dockerignore"
            dest.write_text(f.fix_action.new_content, encoding="utf-8")
            written.append(dest)
    return written
