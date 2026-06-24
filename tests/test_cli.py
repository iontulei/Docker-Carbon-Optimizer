"""CLI integration tests for dco."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dco.cli import app

runner = CliRunner()
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestAnalyze:
    def test_analyze_produces_output(self):
        result = runner.invoke(app, ["analyze", str(FIXTURES_DIR / "simple_python.Dockerfile")])
        assert result.exit_code == 0

    def test_analyze_missing_file(self):
        result = runner.invoke(app, ["analyze", "/nonexistent/Dockerfile"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Error" in result.output

    def test_analyze_json_format(self):
        result = runner.invoke(
            app, ["analyze", str(FIXTURES_DIR / "simple_python.Dockerfile"), "--format", "json"]
        )
        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.output)
        assert "findings" in data
        assert "summary" in data

    def test_analyze_csv_format(self):
        result = runner.invoke(
            app, ["analyze", str(FIXTURES_DIR / "simple_python.Dockerfile"), "--format", "csv"]
        )
        assert result.exit_code == 0
        assert "rule_id" in result.output  # CSV header

    def test_analyze_no_findings_message(self):
        """With no rules registered, analyze should show no issues."""
        result = runner.invoke(app, ["analyze", str(FIXTURES_DIR / "simple_python.Dockerfile")])
        assert result.exit_code == 0


class TestFix:
    def test_fix_no_findings(self):
        """With no rules registered, fix should report no issues."""
        result = runner.invoke(app, ["fix", str(FIXTURES_DIR / "simple_python.Dockerfile")])
        assert result.exit_code == 0

    def test_fix_missing_file(self):
        result = runner.invoke(app, ["fix", "/nonexistent/Dockerfile"])
        assert result.exit_code == 1

    def test_fix_dry_run_with_mock_rule(self, mock_rule):
        result = runner.invoke(
            app,
            ["fix", str(FIXTURES_DIR / "simple_python.Dockerfile"), "--dry-run"],
        )
        assert result.exit_code == 0
        assert "Changes" in result.output or "Applied" in result.output

    def test_fix_creates_optimized_file(self, mock_rule, tmp_path):
        # Copy fixture to tmp
        src = FIXTURES_DIR / "simple_python.Dockerfile"
        dest = tmp_path / "Dockerfile"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        result = runner.invoke(
            app,
            ["fix", str(dest), "--output", str(tmp_path / "Dockerfile.optimized")],
        )
        assert result.exit_code == 0
        optimized = tmp_path / "Dockerfile.optimized"
        assert optimized.exists()
        assert "python:3.12-slim" in optimized.read_text(encoding="utf-8")

    def test_fix_selective_rules(self, mock_rule, tmp_path):
        src = FIXTURES_DIR / "simple_python.Dockerfile"
        dest = tmp_path / "Dockerfile"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        # TEST001 is the mock rule - should apply
        result = runner.invoke(
            app,
            ["fix", str(dest), "--rules", "TEST001", "--output", str(tmp_path / "out.Dockerfile")],
        )
        assert result.exit_code == 0

    def test_fix_in_place(self, mock_rule, tmp_path):
        src = FIXTURES_DIR / "simple_python.Dockerfile"
        dest = tmp_path / "Dockerfile"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        result = runner.invoke(
            app,
            ["fix", str(dest), "--in-place"],
            input="y\n",
        )
        assert result.exit_code == 0
        assert "python:3.12-slim" in dest.read_text(encoding="utf-8")


class TestBatch:
    def test_batch_finds_dockerfiles(self):
        result = runner.invoke(app, ["batch", str(FIXTURES_DIR)])
        assert result.exit_code == 0
        assert "Found" in result.output
        assert "Batch summary" in result.output

    def test_batch_invalid_directory(self):
        result = runner.invoke(app, ["batch", "/nonexistent/dir"])
        assert result.exit_code == 1


class TestVersion:
    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
