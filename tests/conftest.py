"""Shared test fixtures for DCO tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dco.parser import ParsedDockerfile, parse_string
from dco.rules import Finding, FixAction, register, reset_registry

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def simple_python_dockerfile():
    return (FIXTURES_DIR / "simple_python.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def slim_python_dockerfile():
    return (FIXTURES_DIR / "slim_python.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def dev_deps_dockerfile():
    return (FIXTURES_DIR / "dev_deps_left.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def no_multistage_go_dockerfile():
    return (FIXTURES_DIR / "no_multistage_go.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def clean_multistage_dockerfile():
    return (FIXTURES_DIR / "clean_multistage.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def uncombined_runs_dockerfile():
    return (FIXTURES_DIR / "uncombined_runs.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def oversized_python_dockerfile():
    return (FIXTURES_DIR / "oversized_python.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def unpinned_tag_dockerfile():
    return (FIXTURES_DIR / "unpinned_tag.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def pinned_tag_dockerfile():
    return (FIXTURES_DIR / "pinned_tag.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def expected_fixed_base_image():
    return (FIXTURES_DIR / "expected_fixed_base_image.Dockerfile").read_text(encoding="utf-8")


@pytest.fixture
def empty_dockerfile():
    return ""


@pytest.fixture
def parsed_simple_python(simple_python_dockerfile):
    return parse_string(simple_python_dockerfile)


@pytest.fixture
def parsed_slim_python(slim_python_dockerfile):
    return parse_string(slim_python_dockerfile)


@pytest.fixture
def parsed_oversized_python(oversized_python_dockerfile):
    return parse_string(oversized_python_dockerfile)


@pytest.fixture
def parsed_unpinned_tag(unpinned_tag_dockerfile):
    return parse_string(unpinned_tag_dockerfile)


@pytest.fixture
def parsed_pinned_tag(pinned_tag_dockerfile):
    return parse_string(pinned_tag_dockerfile)


@pytest.fixture
def parsed_clean_multistage(clean_multistage_dockerfile):
    return parse_string(clean_multistage_dockerfile)


@pytest.fixture
def mock_rule():
    """Register a fake rule for testing the pipeline. Cleans up after the test."""
    @register
    class MockRule:
        rule_id = "TEST001"
        name = "Test Rule"
        description = "A mock rule for testing"

        def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
            if not parsed_dockerfile.instructions:
                return []
            return [
                Finding(
                    rule_id="TEST001",
                    severity="high",
                    line=0,
                    issue="Test issue: oversized base image",
                    fix="Use a slim variant",
                    size_saved_mb=100.0,
                    original_size_mb=900.0,
                    auto_fixable=True,
                    fix_action=FixAction(
                        action_type="replace_from",
                        target_lines=(0, 0),
                        new_content="FROM python:3.12-slim\n",
                    ),
                )
            ]

    yield MockRule
    reset_registry()
