"""Tests for DCO001: Oversized base image rule."""

from __future__ import annotations

import pytest

from dco.parser import parse_string
from dco.rules.base_image import BaseImageRule


@pytest.fixture
def rule():
    return BaseImageRule()


# --- Fixture-based tests ---


class TestBaseImageFixture:
    """Tests using Dockerfile fixture files."""

    def test_detects_oversized_python(self, rule, parsed_oversized_python):
        findings = rule.check(parsed_oversized_python, {})

        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == "DCO001"
        assert f.severity == "high"
        assert f.line == 0
        assert f.size_saved_mb > 300
        assert f.original_size_mb == pytest.approx(391.6)
        assert f.auto_fixable is False

    def test_fix_action_present_despite_not_auto_fixable(
        self, rule, parsed_oversized_python
    ):
        """DCO001 is not auto-fixable by default but carries a fix_action
        that can be applied with --force."""
        findings = rule.check(parsed_oversized_python, {})

        f = findings[0]
        assert f.auto_fixable is False
        assert f.fix_action is not None
        assert f.fix_action.action_type == "replace_from"
        assert f.fix_action.target_lines == (0, 0)
        assert f.fix_action.new_content == "FROM python:3.12-slim\n"

    def test_fix_skipped_without_force(self, rule, parsed_oversized_python):
        from dco.fixer import apply_fixes

        findings = rule.check(parsed_oversized_python, {})
        result = apply_fixes(parsed_oversized_python.content, findings)
        assert not result.has_changes

    def test_fix_applied_with_force(
        self, rule, parsed_oversized_python, expected_fixed_base_image
    ):
        from dco.fixer import apply_fixes

        findings = rule.check(parsed_oversized_python, {})
        result = apply_fixes(
            parsed_oversized_python.content, findings, force=True
        )
        assert result.fixed_content == expected_fixed_base_image

    def test_skips_slim_python(self, rule, parsed_slim_python):
        findings = rule.check(parsed_slim_python, {})
        assert findings == []

    def test_no_findings_on_empty(self, rule):
        parsed = parse_string("")
        findings = rule.check(parsed, {})
        assert findings == []


# --- Inline edge-case tests ---


class TestBaseImageEdgeCases:
    """Targeted edge-case tests using inline Dockerfile strings."""

    def test_skips_alpine_variant(self, rule):
        parsed = parse_string("FROM python:3.12-alpine\nCMD ['python']\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_preserves_as_alias(self, rule):
        parsed = parse_string("FROM python:3.12 AS builder\nRUN pip install flask\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert "AS builder" in findings[0].fix_action.new_content

    def test_handles_library_prefix(self, rule):
        parsed = parse_string("FROM library/python:3.12\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert findings[0].fix_action.new_content == "FROM python:3.12-slim\n"

    def test_fix_message_warns_about_slim(self, rule):
        parsed = parse_string("FROM python:3.12\nCMD ['python']\n")
        findings = rule.check(parsed, {})
        assert "Slim images remove build tools" in findings[0].fix

    def test_unknown_image_no_findings(self, rule):
        parsed = parse_string("FROM mycompany/custom-image:1.0\nCMD ['/app']\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_multiple_from_instructions(self, rule):
        dockerfile = (
            "FROM python:3.12 AS builder\n"
            "RUN pip install flask\n"
            "FROM python:3.12-slim\n"
            "COPY --from=builder /app /app\n"
        )
        parsed = parse_string(dockerfile)
        findings = rule.check(parsed, {})

        # Only the first FROM (non-slim) should trigger
        assert len(findings) == 1
        assert "AS builder" in findings[0].fix_action.new_content

    def test_handles_no_tag(self, rule):
        parsed = parse_string("FROM python\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        # Should still detect oversized image (uses highest version in data)
        assert len(findings) == 1
        assert findings[0].rule_id == "DCO001"
        assert findings[0].size_saved_mb > 0

    def test_detects_node_oversized(self, rule):
        parsed = parse_string("FROM node:22\nCMD ['node']\n")
        findings = rule.check(parsed, {})

        # node:22 should have a slim alternative in the data
        if findings:
            assert findings[0].rule_id == "DCO001"
            assert findings[0].auto_fixable is False
            assert "slim" in findings[0].fix_action.new_content

    def test_scratch_no_findings(self, rule):
        parsed = parse_string("FROM scratch\nCOPY app /app\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_minimal_image_no_findings(self, rule):
        parsed = parse_string("FROM alpine:3.19\nRUN apk add python3\n")
        findings = rule.check(parsed, {})
        assert findings == []

    def test_distroless_no_findings(self, rule):
        parsed = parse_string(
            "FROM gcr.io/distroless/python3-debian12\nCMD ['app.py']\n"
        )
        findings = rule.check(parsed, {})
        assert findings == []

    def test_finding_issue_text(self, rule):
        parsed = parse_string("FROM python:3.12\nCMD ['python']\n")
        findings = rule.check(parsed, {})

        assert len(findings) == 1
        assert "python" in findings[0].issue
        assert "3.12" in findings[0].issue
        assert "slim" in findings[0].fix.lower() or "slim" in findings[0].fix
