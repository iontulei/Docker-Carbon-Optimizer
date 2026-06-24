"""Tests for DCO005: Missing Multi-stage Build."""

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


import dco.rules.multistage  # noqa: E402, F401


def _check(content: str):
    from dco.rules.multistage import MultistageRule

    rule = MultistageRule()
    parsed = parse_string(content)
    return rule.check(parsed, {"dockerfile_dir": None})


# ---- positive cases ----


def test_go_single_stage_detected():
    content = FIXTURES.joinpath("no_multistage_go.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    assert len(findings) == 1
    assert findings[0].rule_id == "DCO005"
    assert findings[0].severity == "medium"


def test_rust_single_stage_detected():
    content = (
        "FROM rust:1.75\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "RUN cargo build --release\n"
        "CMD [\"./target/release/myapp\"]\n"
    )
    findings = _check(content)
    assert len(findings) == 1
    assert "rust:1.75" in findings[0].issue


def test_maven_single_stage_detected():
    content = (
        "FROM maven:3.9\n"
        "COPY . /app\n"
        "WORKDIR /app\n"
        "RUN mvn package -DskipTests\n"
        "CMD [\"java\", \"-jar\", \"target/app.jar\"]\n"
    )
    findings = _check(content)
    assert len(findings) == 1


def test_not_auto_fixable():
    content = FIXTURES.joinpath("no_multistage_go.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    assert findings[0].auto_fixable is False
    assert findings[0].fix_action is None


# ---- negative cases ----


def test_already_multistage_no_finding():
    content = FIXTURES.joinpath("clean_multistage.Dockerfile").read_text(encoding="utf-8")
    findings = _check(content)
    assert findings == []


def test_interpreted_language_no_finding():
    content = "FROM python:3.12\nRUN pip install flask\n"
    findings = _check(content)
    assert findings == []


def test_compiled_image_no_build_command_no_finding():
    content = "FROM golang:1.21\nCOPY ./binary /app\nCMD [\"/app\"]\n"
    findings = _check(content)
    assert findings == []


def test_empty_dockerfile():
    findings = _check("")
    assert findings == []
