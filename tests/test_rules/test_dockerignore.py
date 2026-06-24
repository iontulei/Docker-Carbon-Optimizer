"""Tests for DCO004: Missing .dockerignore."""

from __future__ import annotations

import pytest

from dco.parser import parse_string
from dco.rules import reset_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    reset_registry()


import dco.rules.dockerignore  # noqa: E402, F401


def _check(content: str, context: dict):
    from dco.rules.dockerignore import DockerignoreRule

    rule = DockerignoreRule()
    parsed = parse_string(content)
    return rule.check(parsed, context)


DOCKERFILE = "FROM python:3.12\nRUN pip install flask\n"


# ---- positive cases ----


def test_missing_dockerignore_detected(tmp_path):
    ctx = {"dockerfile_dir": tmp_path}
    findings = _check(DOCKERFILE, ctx)
    assert len(findings) == 1
    assert findings[0].rule_id == "DCO004"
    assert findings[0].severity == "low"
    assert findings[0].auto_fixable is True


def test_fix_action_contains_template(tmp_path):
    findings = _check(DOCKERFILE, {"dockerfile_dir": tmp_path})
    template = findings[0].fix_action.new_content
    assert ".git" in template
    assert findings[0].fix_action.action_type == "generate_dockerignore"
    assert findings[0].fix_action.target_lines == (-1, -1)


def test_language_detection_python(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask\n")
    findings = _check(DOCKERFILE, {"dockerfile_dir": tmp_path})
    template = findings[0].fix_action.new_content
    assert "__pycache__" in template
    assert ".pytest_cache" in template


# ---- negative cases ----


def test_existing_dockerignore_no_finding(tmp_path):
    (tmp_path / ".dockerignore").write_text(".git\nnode_modules\n")
    findings = _check(DOCKERFILE, {"dockerfile_dir": tmp_path})
    assert findings == []


def test_no_dockerfile_dir_no_finding():
    findings = _check(DOCKERFILE, {})
    assert findings == []
