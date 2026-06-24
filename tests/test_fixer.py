"""Tests for dco.fixer module."""

from __future__ import annotations

from dco.fixer import FixResult, apply_fixes, validate_fix, write_fix
from dco.rules import Finding, FixAction


def _make_finding(
    rule_id="TEST001",
    line=0,
    target_lines=(0, 0),
    new_content="FROM python:3.12-slim\n",
    auto_fixable=True,
    action_type="replace_from",
) -> Finding:
    """Helper to create a Finding with a FixAction."""
    return Finding(
        rule_id=rule_id,
        severity="high",
        line=line,
        issue="Test issue",
        fix="Test fix",
        size_saved_mb=100.0,
        original_size_mb=900.0,
        auto_fixable=auto_fixable,
        fix_action=FixAction(
            action_type=action_type,
            target_lines=target_lines,
            new_content=new_content,
        )
        if auto_fixable
        else None,
    )


class TestApplyFixes:
    def test_single_replace_fix(self, simple_python_dockerfile):
        finding = _make_finding(
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim\n",
        )
        result = apply_fixes(simple_python_dockerfile, [finding])
        assert result.has_changes
        assert result.fixed_content.startswith("FROM python:3.12-slim\n")
        assert len(result.applied_fixes) == 1

    def test_combine_runs_fix(self, simple_python_dockerfile):
        """Combine 3 separate RUN lines into one."""
        combined = "RUN apt-get update && apt-get install -y curl && pip install flask gunicorn\n"
        finding = _make_finding(
            rule_id="TEST002",
            line=1,
            target_lines=(1, 3),
            new_content=combined,
            action_type="combine_runs",
        )
        result = apply_fixes(simple_python_dockerfile, [finding])
        assert result.has_changes
        assert combined.strip() in result.fixed_content
        # Original had 7 lines of instructions, after combining 3 RUNs into 1 we lose 2 lines
        original_lines = simple_python_dockerfile.splitlines()
        fixed_lines = result.fixed_content.splitlines()
        assert len(fixed_lines) == len(original_lines) - 2

    def test_multiple_fixes_bottom_to_top(self, simple_python_dockerfile):
        """Two fixes: replace FROM (line 0) and combine RUNs (lines 1-3)."""
        fix_from = _make_finding(
            rule_id="DCO001",
            line=0,
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim\n",
        )
        fix_runs = _make_finding(
            rule_id="DCO002",
            line=1,
            target_lines=(1, 3),
            new_content="RUN apt-get update && apt-get install -y curl && pip install flask gunicorn\n",
            action_type="combine_runs",
        )
        result = apply_fixes(simple_python_dockerfile, [fix_from, fix_runs])
        assert result.has_changes
        assert result.fixed_content.startswith("FROM python:3.12-slim\n")
        assert "apt-get update && apt-get install" in result.fixed_content
        assert len(result.applied_fixes) == 2

    def test_fixes_sorted_regardless_of_input_order(self, simple_python_dockerfile):
        """Fixes provided in wrong order should still apply correctly."""
        fix_from = _make_finding(
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim\n",
        )
        fix_cmd = _make_finding(
            rule_id="TEST002",
            line=6,
            target_lines=(6, 6),
            new_content='CMD ["python", "-m", "gunicorn", "app:app"]\n',
        )
        # Provide in wrong order (line 6 before line 0)
        result = apply_fixes(simple_python_dockerfile, [fix_cmd, fix_from])
        assert result.has_changes
        assert result.fixed_content.startswith("FROM python:3.12-slim\n")
        assert 'CMD ["python", "-m", "gunicorn", "app:app"]' in result.fixed_content
        assert len(result.applied_fixes) == 2

    def test_no_fixable_findings(self, simple_python_dockerfile):
        finding = _make_finding(auto_fixable=False)
        result = apply_fixes(simple_python_dockerfile, [finding])
        assert not result.has_changes
        assert result.fixed_content == simple_python_dockerfile
        assert len(result.applied_fixes) == 0
        assert len(result.skipped_fixes) == 1

    def test_rules_filter(self, simple_python_dockerfile):
        fix_a = _make_finding(
            rule_id="DCO001",
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim\n",
        )
        fix_b = _make_finding(
            rule_id="DCO002",
            line=1,
            target_lines=(1, 1),
            new_content="RUN apt-get update && apt-get install -y curl\n",
            action_type="combine_runs",
        )
        result = apply_fixes(
            simple_python_dockerfile, [fix_a, fix_b], rules_filter={"DCO001"}
        )
        assert len(result.applied_fixes) == 1
        assert result.applied_fixes[0].rule_id == "DCO001"

    def test_empty_dockerfile(self):
        result = apply_fixes("", [])
        assert not result.has_changes
        assert result.fixed_content == ""

    def test_has_changes_false_when_no_fixes(self, simple_python_dockerfile):
        result = apply_fixes(simple_python_dockerfile, [])
        assert not result.has_changes

    def test_overlapping_fix_ranges(self, simple_python_dockerfile):
        """Two fixes targeting overlapping lines - second should be skipped."""
        fix_a = _make_finding(
            rule_id="DCO001",
            line=0,
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim\n",
        )
        fix_b = _make_finding(
            rule_id="DCO006",
            line=0,
            target_lines=(0, 0),
            new_content="FROM python:3.12-slim@sha256:abc123\n",
        )
        result = apply_fixes(simple_python_dockerfile, [fix_a, fix_b])
        # One applied, one skipped due to overlap
        assert len(result.applied_fixes) == 1
        assert len(result.skipped_fixes) == 1


class TestValidateFix:
    def test_valid_dockerfile(self):
        assert validate_fix("FROM python:3.12\nRUN echo hello\n") is True

    def test_empty_content_is_invalid(self):
        assert validate_fix("") is False

    def test_no_from_is_invalid(self):
        assert validate_fix("RUN echo hello\n") is False


class TestWriteFix:
    def test_write_fix_creates_file(self, tmp_path, simple_python_dockerfile):
        fix_result = FixResult(
            original_content=simple_python_dockerfile,
            fixed_content="FROM python:3.12-slim\nCOPY . /app\n",
        )
        output = tmp_path / "Dockerfile.optimized"
        write_fix(fix_result, output)
        assert output.exists()
        assert output.read_text(encoding="utf-8") == fix_result.fixed_content
