# Dockerfile Carbon Optimizer - Testing Plan

## Overview

This document covers the testing strategy for the Dockerfile Carbon Optimizer (DCO) tool, including unit testing, integration testing, validation testing, and environment considerations.

---

## 1. Test Structure

```
tests/
├── conftest.py                  # Shared fixtures, helper functions
├── fixtures/                    # Sample Dockerfiles for testing
│   ├── simple_python.Dockerfile
│   ├── slim_python.Dockerfile
│   ├── oversized_node.Dockerfile
│   ├── uncombined_runs.Dockerfile
│   ├── combined_runs.Dockerfile
│   ├── dev_deps_left.Dockerfile
│   ├── dev_deps_cleaned.Dockerfile
│   ├── no_multistage_go.Dockerfile
│   ├── clean_multistage.Dockerfile
│   ├── unpinned_tag.Dockerfile
│   ├── pinned_tag.Dockerfile
│   ├── empty.Dockerfile
│   └── complex_real_world.Dockerfile
├── test_parser.py               # Dockerfile parser tests
├── test_rules/
│   ├── test_base_image.py       # DCO001 tests
│   ├── test_run_layers.py       # DCO002 tests
│   ├── test_dev_deps.py         # DCO003 tests
│   ├── test_dockerignore.py     # DCO004 tests
│   ├── test_multistage.py       # DCO005 tests
│   └── test_pinning.py          # DCO006 tests
├── test_carbon/
│   ├── test_network.py          # Network energy model tests
│   ├── test_pull_frequency.py   # Docker Hub API client tests
│   ├── test_model.py            # Combined carbon model tests
│   └── test_build.py            # Energy measurement tests
├── test_fixer.py                # Auto-fix engine tests
└── test_cli.py                  # CLI integration tests (analyze + fix)
```

---

## 2. Unit Tests

### 2.1 Parser Tests (`test_parser.py`)

Test that the parser correctly wraps `dockerfile-parse` and extracts structured data.

```python
# What to test:
- Parse a simple Dockerfile -> returns list of instructions
- Extract FROM instruction -> correct image name and tag
- Extract RUN instructions -> correct command text and line numbers
- Handle multi-line RUN with backslash continuation
- Handle empty Dockerfile -> returns empty list
- Handle Dockerfile with comments -> comments are skipped
- Handle multiple FROM instructions (multi-stage) -> all stages detected
- Handle ARG before FROM -> ARG is captured
```

### 2.2 Rule Tests

Each rule gets positive tests (should trigger) and negative tests (should NOT trigger).

**DCO001 - Base Image (`test_base_image.py`):**
```
Positive cases:
- FROM python:3.12         -> suggests python:3.12-slim, ~855 MB saved
- FROM node:20             -> suggests node:20-slim or node:20-alpine
- FROM ruby:3.2            -> suggests ruby:3.2-slim
- FROM ubuntu:22.04        -> suggests ubuntu:22.04 is fine (no smaller official alt)

Negative cases:
- FROM python:3.12-slim    -> no finding
- FROM alpine:3.19         -> no finding (already minimal)
- FROM scratch             -> no finding
- FROM custom-image:latest -> no finding (unknown image, skip)
```

**DCO002 - RUN Layers (`test_run_layers.py`):**
```
Positive cases:
- 3 consecutive RUN apt-get install -> combine into 1
- RUN pip install a \n RUN pip install b -> combine
- 4 separate RUN commands all running shell commands -> combine

Negative cases:
- Single RUN command -> no finding
- RUN commands with different purposes (apt-get then pip) -> may or may not combine
- Already combined with && -> no finding
```

**DCO003 - Dev Dependencies (`test_dev_deps.py`):**
```
Positive cases:
- RUN apt-get install gcc build-essential -> flag gcc, build-essential
- RUN apk add --no-cache python3-dev -> flag python3-dev
- Install gcc but no corresponding purge/remove -> flag

Negative cases:
- Install gcc + later RUN apt-get purge gcc -> no finding
- No package installation commands -> no finding
- Only production packages (nginx, curl) -> no finding
```

**DCO004 - Dockerignore (`test_dockerignore.py`):**
```
Positive cases:
- Dockerfile in directory with no .dockerignore -> flag
- .dockerignore exists but doesn't exclude .git -> flag

Negative cases:
- .dockerignore exists and excludes common dirs -> no finding
```

**DCO005 - Multi-stage (`test_multistage.py`):**
```
Positive cases:
- FROM golang:1.21 + RUN go build -> suggests multi-stage
- FROM rust:1.75 + RUN cargo build -> suggests multi-stage
- FROM maven:3.9 + RUN mvn package -> suggests multi-stage

Negative cases:
- Already uses multi-stage (2+ FROM instructions) -> no finding
- FROM python:3.12 (interpreted language, no compile step) -> no finding
```

**DCO006 - Pinning (`test_pinning.py`):**
```
Positive cases:
- FROM python -> no tag at all (defaults to :latest)
- FROM python:latest -> explicit latest
- FROM python:3 -> major-only pin

Negative cases:
- FROM python:3.12.1 -> fully pinned, no finding
- FROM python:3.12-slim -> minor-pinned, acceptable
- FROM ubuntu:22.04 -> pinned to specific release
```

### 2.3 Carbon Model Tests

**Network model (`test_network.py`):**
```
- 2015 baseline: 0.06 kWh/GB
- 2017 (1 halving): ~0.03 kWh/GB
- 2019 (2 halvings): ~0.015 kWh/GB
- Custom year input returns correct halved value
- Edge case: year before 2015 returns baseline
```

**Pull frequency (`test_pull_frequency.py`):**
```
- Mock Docker Hub API response -> correct pull_count extraction
- Calculate monthly pulls from total pulls and registration date
- Handle missing/private images -> graceful fallback
- Handle API timeout -> return None, use default
- Respect --pulls-per-month override
```

**Combined model (`test_model.py`):**
```
- Known inputs -> expected CO2 output (hand-calculated)
- 855 MB saved, 100K pulls/month, world average grid -> ~X kg CO2/month
- Zero size saved -> zero CO2
- Different regions -> different CO2 (Netherlands vs India)
```

### 2.4 Fixer Engine Tests (`test_fixer.py`)

Test that the fixer correctly applies FixActions to produce valid optimized Dockerfiles.

```python
# What to test:

# Single fix application:
- Apply DCO001 fix (replace FROM line) -> correct base image in output
- Apply DCO002 fix (combine RUNs) -> single RUN with && in output
- Apply DCO003 fix (append purge) -> purge command appended to correct RUN
- Apply DCO006 fix (pin tag) -> pinned tag in FROM line

# Multiple fixes on same Dockerfile:
- Apply DCO001 + DCO002 together -> both changes present in output
- Apply all fixable rules on a complex Dockerfile -> valid output

# Line offset handling:
- Fixes applied bottom-to-top don't corrupt line numbers
- Combining 3 RUN lines into 1 correctly adjusts subsequent line references

# Edge cases:
- No auto-fixable findings -> output identical to input
- DCO005 finding (not auto-fixable) -> skipped, no crash
- Empty Dockerfile -> no crash, no output file

# Output modes:
- Default: writes to Dockerfile.optimized
- --in-place: overwrites original (test with temp file)
- --dry-run: prints diff but writes nothing
- --output-path custom.Dockerfile: writes to specified path
- --rules "DCO001,DCO002": only applies specified rules

# Validation:
- Output Dockerfile can be re-parsed by dockerfile-parse without errors
- Output Dockerfile re-analyzed by dco produces fewer/no findings
```

### 2.5 Fixer Template Tests

```python
# .dockerignore generation (DCO004 fix):
- Python project -> includes __pycache__/, .venv/, *.py[cod]
- Node project -> includes node_modules/, npm-debug.log
- Go project -> includes vendor/, *.test
- Unknown language -> uses default template with .git, .env, .idea/
- Generated file is valid (no syntax errors, each line is a valid pattern)
```

---

## 3. Integration Tests (`test_cli.py`)

Test the full CLI pipeline end-to-end.

```python
# Test: analyze command produces table output
def test_analyze_produces_table():
    result = runner.invoke(app, ["analyze", "tests/fixtures/simple_python.Dockerfile"])
    assert result.exit_code == 0
    assert "DCO001" in result.stdout
    assert "slim" in result.stdout

# Test: analyze with --format json
def test_analyze_json_output():
    result = runner.invoke(app, ["analyze", "fixtures/simple_python.Dockerfile", "--format", "json"])
    data = json.loads(result.stdout)
    assert len(data["findings"]) > 0

# Test: analyze with --format csv
def test_analyze_csv_output():
    result = runner.invoke(app, ["analyze", "fixtures/simple_python.Dockerfile", "--format", "csv"])
    assert "rule_id,severity,line" in result.stdout

# Test: batch command
def test_batch_analyzes_directory():
    result = runner.invoke(app, ["batch", "tests/fixtures/"])
    assert result.exit_code == 0

# Test: nonexistent file
def test_analyze_missing_file():
    result = runner.invoke(app, ["analyze", "nonexistent.Dockerfile"])
    assert result.exit_code != 0

# Test: --no-dockerhub flag skips API calls
def test_no_dockerhub_flag():
    result = runner.invoke(app, ["analyze", "fixtures/simple_python.Dockerfile", "--no-dockerhub"])
    assert result.exit_code == 0

# ---- dco fix command tests ----

# Test: fix command creates optimized file
def test_fix_creates_optimized_file(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\nRUN apt-get update\nRUN apt-get install -y curl\n")
    result = runner.invoke(app, ["fix", str(dockerfile)])
    assert result.exit_code == 0
    optimized = tmp_path / "Dockerfile.optimized"
    assert optimized.exists()
    content = optimized.read_text()
    assert "slim" in content  # DCO001 fix applied

# Test: fix --dry-run doesn't write files
def test_fix_dry_run(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\n")
    result = runner.invoke(app, ["fix", str(dockerfile), "--dry-run"])
    assert result.exit_code == 0
    assert not (tmp_path / "Dockerfile.optimized").exists()

# Test: fix --in-place overwrites original
def test_fix_in_place(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\n")
    result = runner.invoke(app, ["fix", str(dockerfile), "--in-place"], input="y\n")
    assert result.exit_code == 0
    assert "slim" in dockerfile.read_text()

# Test: fix --rules filters which rules to apply
def test_fix_selective_rules(tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12\nRUN apt-get update\nRUN apt-get install curl\n")
    result = runner.invoke(app, ["fix", str(dockerfile), "--rules", "DCO001"])
    content = (tmp_path / "Dockerfile.optimized").read_text()
    assert "slim" in content           # DCO001 applied
    assert content.count("RUN") == 2   # DCO002 NOT applied (not in --rules)

# Test: fix on clean Dockerfile produces identical output
def test_fix_clean_dockerfile(tmp_path):
    original = "FROM python:3.12-slim\nRUN apt-get update && apt-get install -y curl\n"
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(original)
    result = runner.invoke(app, ["fix", str(dockerfile)])
    assert result.exit_code == 0
    # No changes needed -> either no file written or identical content
```

---

## 4. Validation Testing (30-50 Real Dockerfiles)

### 4.1 Dockerfile Collection

Use `validation/collect_dockerfiles.py` to fetch Dockerfiles from popular OSS repos:
- Search GitHub API for repos with >1000 stars that contain a Dockerfile
- Target diverse languages: Python, Node.js, Go, Java, Ruby, Rust, PHP
- Save each with metadata (repo name, stars, language)

**Target repos (examples):**
- Python: flask, django, fastapi, celery, airflow
- Node.js: express, next.js, nestjs
- Go: kubernetes, prometheus, grafana, traefik
- Java: spring-boot, elasticsearch
- Ruby: rails, gitlab
- Rust: ripgrep, alacritty
- Multi-language: vscode, tensorflow

### 4.2 Validation Process

```bash
# Step 1: Analyze all collected Dockerfiles
dco batch validation/dockerfiles/ --format csv --output validation/results/findings.csv --no-dockerhub

# Step 2: Auto-fix all collected Dockerfiles
for f in validation/dockerfiles/*.Dockerfile; do
    dco fix "$f" --output-path "validation/results/fixed/$(basename $f)"
done

# Step 3: For 10-15 Dockerfiles, build BOTH original and fixed versions
# Compare: docker image ls (before vs after) to verify size reduction claims

# Step 4: For 5-10 Dockerfiles, measure build energy with CodeCarbon
# Run each build 5 times, report median

# Step 5: Re-analyze the fixed Dockerfiles to verify fixes resolved the issues
dco batch validation/results/fixed/ --format csv --output validation/results/post_fix_findings.csv

# Step 6: Aggregate statistics
python validation/run_validation.py --summarize
```

### 4.3 Metrics to Report

- Total Dockerfiles analyzed
- Number of findings per rule (which rules trigger most often)
- Average size reduction per finding
- Total potential size savings across all files
- Estimated CO2 savings at various pull frequencies
- False positive rate (manual review of a subset)
- **Auto-fix success rate**: % of findings where auto-fix produced a valid, buildable Dockerfile
- **Fix effectiveness**: re-analyze fixed Dockerfiles - how many findings were resolved?
- **Actual vs estimated size savings**: compare estimated size_saved_mb with real docker image size difference

---

## 5. Environment Reasoning: Where to Run Tests

### Option A: Single Developer Machine

**What it means:** Each team member runs tests on their own laptop/desktop.

**Pros:**
- Simplest setup - no infrastructure needed
- Fast iteration - run tests immediately after code changes
- No cost - uses hardware you already have

**Cons:**
- Different results on different machines (especially energy measurements)
- OS differences may cause test failures (Windows path separators, Docker Desktop vs native Docker)
- Energy measurements are not reproducible across machines (different CPUs, cooling, background load)
- Cannot guarantee Docker is installed on every developer's machine

**Best for:** Unit tests, rule tests, parser tests - anything that doesn't require Docker or energy measurement.

**Verdict:** Good for daily development, insufficient for validation.

---

### Option B: Multiple Physical Machines

**What it means:** Run tests across several machines with different OS/hardware.

**Pros:**
- Cross-platform validation (test on Windows, Linux, macOS)
- Can parallelize validation runs across machines
- Catches platform-specific bugs early
- More realistic energy measurements on bare metal

**Cons:**
- Coordination overhead - who runs what, when
- Hardware differences affect energy measurements (Intel vs AMD vs ARM)
- Difficult to keep environments consistent
- Not all team members may have Docker on all platforms

**Best for:** Cross-platform CLI testing, finding OS-specific bugs.

**Verdict:** Useful for compatibility testing, impractical for reproducible energy measurement.

---

### Option C: Virtual Machines (VMs)

**What it means:** Run tests inside VMs (VirtualBox, VMware, or cloud VMs like AWS EC2).

**Pros:**
- Reproducible environments - same OS, same packages, same Docker version
- Can snapshot and share VM images across team
- Isolation from host machine noise (no random background processes)
- Cloud VMs (EC2, GCP) give access to consistent hardware

**Cons:**
- Energy measurement inside a VM is unreliable - VMs add a virtualization layer that distorts CPU energy readings (RAPL counters may not work, CodeCarbon may report host energy not VM energy)
- Docker-in-Docker adds complexity (nested virtualization)
- Cloud VMs cost money
- Slower than bare metal for builds

**Docker-in-Docker considerations:**
- Running Docker inside a VM means nested virtualization (VM -> Docker container)
- This works but is slower and may complicate energy measurements
- Alternative: use Docker's "sibling containers" approach (mount Docker socket)
- On Windows/macOS, Docker Desktop already runs in a hidden VM, so you'd have VM -> VM -> container

**Best for:** Reproducible functional testing, CI/CD pipelines.

**Verdict:** Good for functional tests, bad for energy measurements.

---

### Option D: CI/CD (GitHub Actions) - Recommended for Functional Tests

**What it means:** Automated tests on every push via GitHub Actions.

**Pros:**
- Runs automatically on every push and PR
- Multi-OS matrix: test on ubuntu-latest, macos-latest, windows-latest simultaneously
- Consistent, clean environment every run
- Free for public repos (2000 minutes/month for private)
- No setup burden on individual developers

**Cons:**
- Cannot do energy measurements (no access to RAPL, no consistent hardware)
- Cannot run Docker builds in the free tier (limited Docker support in Actions)
- Slower feedback loop than local testing (2-5 min for CI run)

**Best for:** Automated functional testing, linting, coverage checks.

---

### Recommended Testing Environment Strategy

| Test Type | Where to Run | Why |
|-----------|-------------|-----|
| Unit tests (rules, parser, carbon math) | Local machine + GitHub Actions CI | Fast, no Docker needed, multi-OS via CI matrix |
| Integration tests (CLI commands) | Local machine + GitHub Actions CI | Tests CLI output, no Docker build needed |
| Docker build size validation | Any machine with Docker installed | Builds real images, compares sizes |
| Energy measurement (CodeCarbon) | One controlled Linux bare-metal machine | Must be bare metal for reliable RAPL readings; same machine for all measurements; no VMs |
| Batch validation (30-50 Dockerfiles) | Any machine with Docker + CI | Functional results don't depend on hardware |

**Key recommendation for energy measurement:**
- Use ONE dedicated Linux machine (bare metal, not VM) for ALL energy measurements
- Run measurements with minimal background processes
- Run each build 5 times, report median and standard deviation
- Document the exact hardware: CPU model, RAM, OS version, Docker version
- This ensures all before/after comparisons are on identical hardware
- University lab machines or a team member's Linux desktop work well for this

**Key recommendation for CI:**
```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python-version: ["3.11", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: pytest tests/ --cov=src/dco --cov-report=term-missing
      - run: pytest tests/ --cov=src/dco --cov-fail-under=80
```

---

## 6. Test Fixtures: Sample Dockerfiles

### `simple_python.Dockerfile` (should trigger DCO001, DCO002)
```dockerfile
FROM python:3.12
RUN apt-get update
RUN apt-get install -y curl
RUN pip install flask gunicorn
COPY . /app
WORKDIR /app
CMD ["gunicorn", "app:app"]
```

### `slim_python.Dockerfile` (should trigger nothing)
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask gunicorn
COPY . /app
WORKDIR /app
CMD ["gunicorn", "app:app"]
```

### `dev_deps_left.Dockerfile` (should trigger DCO003)
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y gcc build-essential python3-dev
RUN pip install numpy pandas
COPY . /app
CMD ["python", "app.py"]
```

### `no_multistage_go.Dockerfile` (should trigger DCO005)
```dockerfile
FROM golang:1.21
WORKDIR /app
COPY . .
RUN go build -o server .
EXPOSE 8080
CMD ["./server"]
```

### `clean_multistage.Dockerfile` (should trigger nothing for DCO005)
```dockerfile
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o server .

FROM gcr.io/distroless/base
COPY --from=builder /app/server /server
EXPOSE 8080
CMD ["/server"]
```

---

## 7. Coverage Targets

| Module | Target | Rationale |
|--------|--------|-----------|
| parser.py | 90% | Core module, must be reliable |
| fixer.py | 85% | Must produce valid Dockerfiles, line-offset logic is tricky |
| fixer_templates.py | 80% | Template output must be valid .dockerignore patterns |
| rules/* | 85% | Each rule needs positive + negative tests + fix output tests |
| carbon/network.py | 95% | Pure math, easy to test exhaustively |
| carbon/pull_frequency.py | 80% | HTTP client, mock external calls |
| carbon/model.py | 90% | Core calculation, must be correct |
| carbon/build.py | 60% | Depends on external tools (CodeCarbon), hard to test in CI |
| cli.py | 75% | Integration surface, tested via CLI runner |
| output.py | 70% | Formatting code, visual verification also needed |
| **Overall** | **80%** | Enforced in CI |

---

## 8. Testing Timeline

| Sprint | Member 1 | Member 2 | Member 3 | Member 4 | Member 5 |
|--------|----------|----------|----------|----------|----------|
| Week 1 | conftest.py, test_parser.py, test_fixer.py, test_cli.py | test_base_image.py (incl. fix), test_pinning.py (incl. fix) | test_run_layers.py (incl. fix), test_dev_deps.py (incl. fix), test_dockerignore.py (incl. fix), test_multistage.py | test_network.py, test_pull_frequency.py, test_model.py | CI pipeline setup, Dockerfile collection |
| Week 2 | Integration test polish (analyze + fix commands) | Verify fixes build correctly | Verify fixes build correctly | test_build.py, energy experiments | Run validation (analyze + fix), report results |
