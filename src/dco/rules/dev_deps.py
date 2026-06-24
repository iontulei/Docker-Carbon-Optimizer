"""DCO003: Detect development dependencies left in production images."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from dco.rules import Finding, FixAction, register

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile

_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "dev_packages.json"
_DEV_PACKAGES: dict[str, dict[str, float]] = {}

# Maps keyword found in the RUN value → (package-manager key, cleanup command).
_APT_CLEANUP = (
    "apt-get purge -y {pkgs} && apt-get autoremove -y "
    "&& rm -rf /var/lib/apt/lists/*"
)

_INSTALL_PATTERNS: list[tuple[str, str, str]] = [
    ("apt-get install", "apt", _APT_CLEANUP),
    ("apt install", "apt", _APT_CLEANUP),
    ("apk add", "apk", "apk del {pkgs}"),
]

_REMOVE_PATTERNS: list[str] = [
    "apt-get purge",
    "apt-get remove",
    "apt purge",
    "apt remove",
    "apk del",
]


def _load_packages() -> dict[str, dict[str, float]]:
    """Load dev_packages.json. Returns ``{manager: {pkg_name: size_mb}}``."""
    global _DEV_PACKAGES
    if _DEV_PACKAGES:
        return _DEV_PACKAGES
    with open(_DATA_FILE, encoding="utf-8") as fh:
        raw = json.load(fh)
    _DEV_PACKAGES = {
        k: v for k, v in raw.items()
        if isinstance(v, dict) and k != "_comment"
    }
    return _DEV_PACKAGES


def _extract_packages(command: str) -> list[str]:
    """Return non-flag tokens from an install/add command string."""
    tokens = command.split()
    packages: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            # Flags like --no-install-recommends, -y, --virtual .build-deps
            if token in ("--virtual",):
                skip_next = True  # next token is the virtual name, not a package
            continue
        packages.append(token)
    return packages


def _find_install_info(
    run_value: str,
) -> tuple[str | None, str | None, list[str], float]:
    """Parse a RUN value and return (mgr_key, cleanup_tpl, pkgs_found, size_mb).

    Returns (None, None, [], 0.0) when no install command is detected.
    """
    dev_pkgs = _load_packages()
    # Split on && to handle combined commands.
    subcommands = re.split(r"\s*&&\s*", run_value)

    for sub in subcommands:
        sub_stripped = sub.strip()
        for pattern, mgr_key, cleanup_tpl in _INSTALL_PATTERNS:
            if pattern not in sub_stripped:
                continue
            # Grab everything after the install keyword.
            idx = sub_stripped.index(pattern) + len(pattern)
            remainder = sub_stripped[idx:]
            tokens = _extract_packages(remainder)
            mgr_data = dev_pkgs.get(mgr_key, {})
            found = [t for t in tokens if t in mgr_data]
            if found:
                size = sum(mgr_data.get(p, 0) for p in found)
                return mgr_key, cleanup_tpl, found, size

    return None, None, [], 0.0


def _is_cleaned(pkg_names: list[str], run_values: list[str]) -> bool:
    """Check whether all *pkg_names* appear in a removal command somewhere in *run_values*."""
    for val in run_values:
        lower = val.lower()
        if any(rp in lower for rp in _REMOVE_PATTERNS):
            if all(p in val for p in pkg_names):
                return True
    return False


@register
class DevDepsRule:
    rule_id = "DCO003"
    name = "Dev Deps in Production"
    description = "Detects development/build dependencies left in the production image."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        instructions = parsed_dockerfile.instructions
        from_instrs = parsed_dockerfile.from_instructions

        # For multi-stage builds, only examine the final stage.
        last_from_line = 0
        if len(from_instrs) >= 2:
            last_from_line = from_instrs[-1]["startline"]

        # Collect RUN instructions in the final stage.
        stage_runs = [
            instr for instr in instructions
            if instr["instruction"] == "RUN" and instr["startline"] > last_from_line
        ]
        # Also keep their values for cleanup scanning.
        all_run_values = [r["value"] for r in stage_runs]

        findings: list[Finding] = []
        for idx, run_instr in enumerate(stage_runs):
            mgr_key, cleanup_tpl, found_pkgs, size_mb = _find_install_info(
                run_instr["value"]
            )
            if not found_pkgs:
                continue

            # Check cleanup in same RUN (subcommands after install) or later RUNs.
            # For the same RUN, only look at subcommands AFTER the install.
            same_run_parts = re.split(r"\s*&&\s*", run_instr["value"])
            install_idx = next(
                (i for i, s in enumerate(same_run_parts)
                 if any(p in s for p in ("install", "add"))),
                -1,
            )
            after_install = same_run_parts[install_idx + 1:] if install_idx >= 0 else []
            later_values = [" && ".join(after_install)] + all_run_values[idx + 1:]

            if _is_cleaned(found_pkgs, later_values):
                continue

            pkg_list = " ".join(found_pkgs)
            cleanup_cmd = cleanup_tpl.format(pkgs=pkg_list) if cleanup_tpl else ""

            # Build replacement: original RUN text + cleanup appended.
            original_text = run_instr["value"]
            new_run_value = f"{original_text} && \\\n    {cleanup_cmd}"
            new_content = f"RUN {new_run_value}\n"

            findings.append(Finding(
                rule_id="DCO003",
                severity="high",
                line=run_instr["startline"],
                issue=(
                    f"Development packages left in production image: "
                    f"{pkg_list} (~{size_mb:.0f} MB)."
                ),
                fix=f"Append cleanup: && {cleanup_cmd}",
                size_saved_mb=size_mb,
                original_size_mb=size_mb,
                auto_fixable=True,
                fix_action=FixAction(
                    action_type="append_to_run",
                    target_lines=(run_instr["startline"], run_instr["endline"]),
                    new_content=new_content,
                ),
            ))

        return findings
