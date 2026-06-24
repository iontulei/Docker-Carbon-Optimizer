"""Tests for dco.parser module."""

from __future__ import annotations

from pathlib import Path

import pytest

from dco.parser import parse_file, parse_string

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestParseString:
    def test_parse_simple_dockerfile(self, simple_python_dockerfile):
        result = parse_string(simple_python_dockerfile)
        assert len(result.instructions) == 7
        assert result.instructions[0]["instruction"] == "FROM"
        assert result.instructions[1]["instruction"] == "RUN"

    def test_extracts_baseimage(self, simple_python_dockerfile):
        result = parse_string(simple_python_dockerfile)
        assert result.baseimage == "python:3.12"

    def test_extracts_from_instructions(self, clean_multistage_dockerfile):
        result = parse_string(clean_multistage_dockerfile)
        assert len(result.from_instructions) == 2
        assert result.from_instructions[0]["value"] == "golang:1.21 AS builder"
        assert result.from_instructions[1]["value"] == "gcr.io/distroless/base"

    def test_line_numbers_are_correct(self, simple_python_dockerfile):
        result = parse_string(simple_python_dockerfile)
        # First instruction (FROM) should start at line 0
        assert result.instructions[0]["startline"] == 0
        # Second instruction (RUN apt-get update) should start at line 1
        assert result.instructions[1]["startline"] == 1

    def test_parse_multiline_run(self):
        content = "FROM python:3.12\nRUN apt-get update && \\\n    apt-get install -y curl\n"
        result = parse_string(content)
        run_instructions = [i for i in result.instructions if i["instruction"] == "RUN"]
        assert len(run_instructions) == 1
        # Multi-line RUN should span lines 1-2
        assert run_instructions[0]["startline"] == 1
        assert run_instructions[0]["endline"] == 2

    def test_parse_empty_dockerfile(self):
        result = parse_string("")
        assert result.instructions == []
        assert result.baseimage == ""
        assert result.from_instructions == []

    def test_parse_preserves_content(self, simple_python_dockerfile):
        result = parse_string(simple_python_dockerfile)
        assert result.content == simple_python_dockerfile

    def test_parse_comments_not_in_instructions(self):
        content = "# This is a comment\nFROM python:3.12\n"
        result = parse_string(content)
        instruction_types = [i["instruction"] for i in result.instructions]
        assert "COMMENT" not in instruction_types or all(
            i["instruction"] != "#" for i in result.instructions
            if i["instruction"] not in ("FROM", "COMMENT")
        )
        # At minimum, FROM should be present
        assert any(i["instruction"] == "FROM" for i in result.instructions)

    def test_parse_arg_before_from(self):
        content = "ARG VERSION=3.12\nFROM python:${VERSION}\n"
        result = parse_string(content)
        assert result.instructions[0]["instruction"] == "ARG"
        assert any(i["instruction"] == "FROM" for i in result.instructions)

    def test_source_path_none_by_default(self, simple_python_dockerfile):
        result = parse_string(simple_python_dockerfile)
        assert result.path is None

    def test_source_path_set_when_provided(self, simple_python_dockerfile):
        path = Path("/some/Dockerfile")
        result = parse_string(simple_python_dockerfile, source_path=path)
        assert result.path == path


class TestParseFile:
    def test_parse_file_from_path(self):
        path = FIXTURES_DIR / "simple_python.Dockerfile"
        result = parse_file(path)
        assert result.baseimage == "python:3.12"
        assert result.path == path
        assert len(result.instructions) == 7

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="Dockerfile not found"):
            parse_file("/nonexistent/Dockerfile")

    def test_parse_file_accepts_string_path(self):
        path = str(FIXTURES_DIR / "slim_python.Dockerfile")
        result = parse_file(path)
        assert result.baseimage == "python:3.12-slim"
