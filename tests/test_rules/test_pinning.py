"""Tests for DCO006: Unpinned base image tag rule."""

from __future__ import annotations

import pytest

from dco.parser import parse_string
from dco.rules.pinning import PinningRule


@pytest.fixture
def rule():
    return PinningRule()


# --- Fixture-based tests ---


class TestPinningFixture:
    """Tests using Dockerfile fixture files."""

    def test_detects_unpinned_tag(self, rule, parsed_unpinned_tag):
        findings = rule.check(parsed_unpinned_tag, {})

        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "DCO006"
        assert f.severity == "low"
        assert f.line == 0
        assert "without a tag" in f.issue

    def test_unpinned_tag_fix_action(self, rule, parsed_unpinned_tag):
        findings = rule.check(parsed_unpinned_tag, {})

        f = findings[0]
        assert f.auto_fixable is True
        assert f.fix_action is not None
        assert f.fix_action.action_type == "pin_tag"
        assert f.fix_action.target_lines == (0, 0)
        # Should pin to a specific version
        assert "python:" in f.fix_action.new_content
        assert "FROM" in f.fix_action.new_content

    def test_skips_pinned_tag(self, rule, parsed_pinned_tag):
        findings = rule.check(parsed_pinned_tag, {})
        assert findings == []

    def test_no_findings_on_slim_python(self, rule, parsed_slim_python):
        # python:3.12-slim has a dot -> pinned
        findings = rule.check(parsed_slim_python, {})
        assert findings == []

    def test_no_findings_on_empty(self, rule):
        parsed = parse_string("")
        findings = rule.check(parsed, {})
        assert findings == []


# --- Inline edge-case tests ---


class TestPinningEdgeCases:
    """Targeted edge-case tests using inline Dockerfile strings."""

    def test_detects_latest_tag(self, rule):
        parsed = parse_string("FROM python:latest\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert "not pinned" in findings[0].issue

    def test_detects_major_only_tag(self, rule):
        parsed = parse_string("FROM python:3\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert findings[0].rule_id == "DCO006"

    def test_skips_minor_version(self, rule):
        parsed = parse_string("FROM python:3.12\nCMD ['python']\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_skips_patch_version(self, rule):
        parsed = parse_string("FROM python:3.12.3\nCMD ['python']\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_skips_variant_tag(self, rule):
        parsed = parse_string("FROM python:3.12-slim\nCMD ['python']\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_skips_scratch(self, rule):
        parsed = parse_string("FROM scratch\nCOPY app /app\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_skips_codename_tag(self, rule):
        parsed = parse_string("FROM debian:bookworm\nRUN apt-get update\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_preserves_as_alias(self, rule):
        parsed = parse_string("FROM python AS builder\nRUN pip install flask\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert findings[0].auto_fixable is True
        assert "AS builder" in findings[0].fix_action.new_content

    def test_unknown_image_not_auto_fixable(self, rule):
        parsed = parse_string("FROM mycompany/custom-image\nCMD ['/app']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert findings[0].auto_fixable is False
        assert findings[0].fix_action is None

    def test_multiple_from_instructions(self, rule):
        dockerfile = (
            "FROM python AS builder\n"
            "RUN pip install flask\n"
            "FROM python:3.12-slim\n"
            "COPY --from=builder /app /app\n"
        )
        parsed = parse_string(dockerfile)
        findings = rule.check(parsed, {})

        # Only the first FROM (unpinned) should trigger
        assert len(findings) == 1
        assert findings[0].line == 0

    def test_latest_tag_fix_pins_version(self, rule):
        parsed = parse_string("FROM node:latest\nCMD ['node']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        f = findings[0]
        if f.auto_fixable:
            assert "node:" in f.fix_action.new_content
            # Should not contain 'latest' anymore
            assert "latest" not in f.fix_action.new_content

    def test_size_saved_is_zero(self, rule):
        # Pinning doesn't save image size directly
        parsed = parse_string("FROM python\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert findings[0].size_saved_mb == 0.0
        assert findings[0].original_size_mb == 0.0

    def test_digest_pinned_is_skipped(self, rule):
        parsed = parse_string(
            "FROM python@sha256:abcdef1234567890\nCMD ['python']\n"
        )
        findings = rule.check(parsed, {})
        assert findings == []
