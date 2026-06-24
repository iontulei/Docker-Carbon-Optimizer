"""Tests for DCO003: Dev Dependencies in Production."""

from __future__ import annotations

from pathlib import Path

import pytest

from dco.parser import parse_string
from dco.rules import reset_registry

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()


import dco.rules.dev_deps  # noqa: E402, F401


def _check(content: str, context: dict | None = None):
    from dco.rules.dev_deps import DevDepsRule

    rule = DevDepsRule()
    parsed = parse_string(content)
    ctx = context or {"dockerfile_dir": None}
    return rule.check(parsed, ctx)


# ---- positive cases ----


def test_dev_deps_detected():
    content = FIXTURES.joinpath("dev_deps_left.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    assert len(findings) == 1
    assert findings[0].rule_id == "DCO003"
    assert findings[0].severity == "high"
    assert "gcc" in findings[0].issue
    assert findings[0].auto_fixable is True


def test_fix_appends_cleanup():
    content = FIXTURES.joinpath("dev_deps_left.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    fix_text = findings[0].fix_action.new_content
    assert "apt-get purge" in fix_text
    assert "autoremove" in fix_text


def test_apk_packages_detected():
    content = (
        "FROM python:3.12-alpine\n"
        "RUN apk add --no-cache gcc musl-dev\n"
        "RUN pip install numpy\n"
    )
    findings = _check(content)
    assert len(findings) == 1
    assert "gcc" in findings[0].issue
    assert "apk del" in findings[0].fix_action.new_content


# ---- negative cases ----


def test_dev_deps_cleaned_later_run_no_finding():
    content = (
        "FROM python:3.12-slim\n"
        "RUN apt-get update && apt-get install -y gcc build-essential\n"
        "RUN pip install numpy\n"
        "RUN apt-get purge -y gcc build-essential && apt-get autoremove -y\n"
    )
    findings = _check(content)
    assert findings == []


def test_dev_deps_cleaned_same_run_no_finding():
    content = (
        "FROM python:3.12-slim\n"
        "RUN apt-get update && apt-get install -y gcc && "
        "pip install numpy && apt-get purge -y gcc && apt-get autoremove -y\n"
    )
    findings = _check(content)
    assert findings == []


def test_multistage_builder_deps_ignored():
    content = (
        "FROM python:3.12-slim AS builder\n"
        "RUN apt-get update && apt-get install -y gcc build-essential\n"
        "RUN pip install numpy\n"
        "FROM python:3.12-slim\n"
        "COPY --from=builder /app /app\n"
    )
    findings = _check(content)
    assert findings == []


def test_no_install_commands():
    content = "FROM python:3.12-slim\nRUN pip install flask\nCOPY . /app\n"
    findings = _check(content)
    assert findings == []


def test_empty_dockerfile():
    findings = _check("")
    assert findings == []
