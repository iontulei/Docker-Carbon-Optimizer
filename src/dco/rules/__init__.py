"""Rule protocol, data types, and registry for DCO rules."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile


@dataclass
class FixAction:
    """Structured instruction for auto-fixing a finding."""

    action_type: str  # "replace_from", "combine_runs", "append_to_run",
    #                   "generate_dockerignore", "pin_tag"
    target_lines: tuple[int, int]  # (start_line, end_line) - 0-indexed; end_line inclusive
    new_content: str  # replacement text


@dataclass
class Finding:
    """A single issue detected in a Dockerfile."""

    rule_id: str  # e.g., "DCO001"
    severity: str  # "high", "medium", "low"
    line: int  # 0-indexed line number
    issue: str  # Human-readable description
    fix: str  # Suggested fix description
    size_saved_mb: float  # Estimated size reduction
    original_size_mb: float  # Original size for carbon calculation
    auto_fixable: bool = False
    fix_action: FixAction | None = None


@runtime_checkable
class Rule(Protocol):
    """Protocol that all DCO rules must satisfy."""

    rule_id: str
    name: str
    description: str

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]: ...


# --- Rule Registry ---

_registry: list[Rule] = []
_discovered: bool = False


def register(rule_class: type) -> type:
    """Class decorator that registers a rule instance in the global registry."""
    instance = rule_class()
    # Prevent duplicate registration
    for existing in _registry:
        if existing.rule_id == instance.rule_id:
            return rule_class
    _registry.append(instance)
    return rule_class


def get_all_rules() -> list[Rule]:
    """Return all registered rules."""
    return list(_registry)


def get_rule(rule_id: str) -> Rule | None:
    """Look up a single rule by ID."""
    for rule in _registry:
        if rule.rule_id == rule_id:
            return rule
    return None


def discover_rules() -> None:
    """Import all rule modules to trigger @register decorators.

    Uses pkgutil to auto-discover .py files in dco/rules/.
    Safe to call multiple times (idempotent).
    """
    global _discovered
    if _discovered:
        return
    import dco.rules as rules_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(rules_pkg.__path__):
        if modname.startswith("_"):
            continue
        importlib.import_module(f"dco.rules.{modname}")
    _discovered = True


def reset_registry() -> None:
    """Clear the registry. Used in tests."""
    global _discovered
    _registry.clear()
    _discovered = False
