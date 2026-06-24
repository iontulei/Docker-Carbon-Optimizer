"""Tests for DCO002: Uncombined RUN Layers."""

from __future__ import annotations

from pathlib import Path

import pytest

from dco.fixer import apply_fixes
from dco.parser import parse_string
from dco.rules import reset_registry

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()


# Force import so @register fires.
import dco.rules.run_layers  # noqa: E402, F401


def _check(content: str):
    from dco.rules.run_layers import RunLayersRule

    rule = RunLayersRule()
    parsed = parse_string(content)
    return rule.check(parsed, {"dockerfile_dir": None})


# ---- positive cases ----


def test_consecutive_runs_detected():
    content = FIXTURES.joinpath("uncombined_runs.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    assert len(findings) == 1
    assert findings[0].rule_id == "DCO002"
    assert findings[0].severity == "medium"
    assert findings[0].auto_fixable is True


def test_two_consecutive_runs_detected():
    content = "FROM ubuntu:22.04\nRUN echo a\nRUN echo b\n"
    findings = _check(content)
    assert len(findings) == 1
    assert "2 consecutive" in findings[0].issue


def test_single_run_no_finding():
    content = "FROM ubuntu:22.04\nRUN echo hello\n"
    findings = _check(content)
    assert findings == []


def test_non_consecutive_runs_separate_groups():
    content = (
        "FROM ubuntu:22.04\n"
        "RUN echo a\n"
        "RUN echo b\n"
        "COPY . /app\n"
        "RUN echo c\n"
        "RUN echo d\n"
    )
    findings = _check(content)
    assert len(findings) == 2


def test_fix_action_combines_correctly():
    content = FIXTURES.joinpath("uncombined_runs.Dockerfile").read_text(encoding="utf-8")
    expected = FIXTURES.joinpath("expected_fixed_runs.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    result = apply_fixes(content, findings)
    assert result.fixed_content == expected


def test_fix_action_line_numbers():
    content = FIXTURES.joinpath("uncombined_runs.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    action = findings[0].fix_action
    # Lines 1-4 (0-indexed) are the 4 RUN instructions.
    assert action.target_lines == (1, 4)


def test_multiline_run_not_split():
    content = (
        "FROM ubuntu:22.04\n"
        "RUN apt-get update && \\\n"
        "    apt-get install -y curl\n"
        "COPY . /app\n"
    )
    findings = _check(content)
    assert findings == []


def test_empty_dockerfile():
    findings = _check("")
    assert findings == []
