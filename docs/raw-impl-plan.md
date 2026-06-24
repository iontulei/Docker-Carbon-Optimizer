# Dockerfile Carbon Optimizer - Implementation Plan

## Technology Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Language | Python 3.11+ | Entire ecosystem is Python-native (dockerfile-parse, CodeCarbon, Docker SDK) |
| CLI framework | Typer | Type-hint-based, auto-generates --help, built on Click, works with Rich |
| Dockerfile parsing | dockerfile-parse | Pure Python, `.structure` returns instruction dicts with line numbers |
| HTTP client | httpx | For Docker Hub API calls (pull counts), supports async |
| Terminal output | Rich | Tables, colors, progress bars for terminal output |
| Energy measurement | CodeCarbon (primary), pyEnergiBridge (secondary) | pip install, wrap build in context manager, returns kWh/CO2 |
| Testing | pytest + pytest-cov | Standard Python testing, with respx for mocking HTTP |
| Linting/Formatting | Ruff | Replaces flake8+black+isort in one tool |
| Packaging | pyproject.toml | `pip install .` adds `dco` command to PATH |

---

## Project Structure

```
dockerfile-carbon-optimizer/
├── pyproject.toml
├── README.md
├── LICENSE (MIT)
├── .github/workflows/ci.yml
├── src/dco/
│   ├── __init__.py
│   ├── cli.py                  # Typer entry point
│   ├── parser.py               # Wraps dockerfile-parse
│   ├── output.py               # Rich table formatter
│   ├── config.py               # Constants, defaults
│   ├── rules/
│   │   ├── __init__.py         # Rule protocol + Finding dataclass + registry
│   │   ├── base_image.py       # DCO001: Oversized base images
│   │   ├── run_layers.py       # DCO002: Uncombined RUN layers
│   │   ├── dev_deps.py         # DCO003: Dev deps left in production
│   │   ├── dockerignore.py     # DCO004: Missing .dockerignore
│   │   ├── multistage.py       # DCO005: Missing multi-stage builds
│   │   └── pinning.py          # DCO006: Unpinned base image tags
│   ├── fixer.py                    # Auto-fix engine: applies FixActions to Dockerfile
│   ├── fixer_templates.py          # .dockerignore templates per language
│   ├── carbon/
│   │   ├── __init__.py
│   │   ├── network.py          # Aslan et al. network transfer model
│   │   ├── build.py            # CodeCarbon/EnergiBridge wrapper
│   │   ├── pull_frequency.py   # Docker Hub API client
│   │   └── model.py            # Combine dimensions into CO2 estimate
│   └── data/
│       ├── image_sizes.json    # Base image -> size mapping
│       ├── dev_packages.json   # Known dev dependency package names
│       └── grid_intensity.json # Country -> gCO2/kWh (IEA 2023)
├── tests/
│   ├── conftest.py             # Shared fixtures (sample Dockerfiles)
│   ├── fixtures/               # Sample Dockerfile files for testing
│   ├── test_parser.py
│   ├── test_rules/
│   │   ├── test_base_image.py
│   │   ├── test_run_layers.py
│   │   ├── test_dev_deps.py
│   │   ├── test_dockerignore.py
│   │   ├── test_multistage.py
│   │   └── test_pinning.py
│   ├── test_carbon/
│   │   ├── test_network.py
│   │   ├── test_pull_frequency.py
│   │   └── test_model.py
│   ├── test_fixer.py               # Auto-fix engine tests
│   └── test_cli.py
└── validation/
    ├── collect_dockerfiles.py  # Script to fetch Dockerfiles from top GH repos
    ├── dockerfiles/            # 30-50 real Dockerfiles
    ├── run_validation.py       # Batch analysis runner
    └── results/                # CSV/JSON output
```

---

## Architecture

### Rule System

Each rule implements a `Rule` protocol:

```python
@dataclass
class Finding:
    rule_id: str              # e.g., "DCO001"
    severity: str             # "high", "medium", "low"
    line: int                 # Dockerfile line number
    issue: str                # Human-readable description
    fix: str                  # Suggested fix
    size_saved_mb: float      # Estimated size reduction
    original_size_mb: float   # For carbon calculation

class Rule(Protocol):
    rule_id: str
    name: str
    description: str
    def check(self, parsed_dockerfile, context: dict) -> list[Finding]: ...
```

Adding a new rule = new file in `rules/` + add to registry list. No other code changes needed.

### Auto-Fix System (dco fix)

Each `Finding` includes structured fix data so the fixer can apply changes automatically:

```python
@dataclass
class FixAction:
    action_type: str          # "replace_from", "combine_runs", "append_to_run",
                              # "generate_dockerignore", "pin_tag"
    target_lines: tuple[int, int]  # start_line, end_line in original
    new_content: str          # replacement text

@dataclass
class Finding:
    # ... existing fields ...
    auto_fixable: bool        # can this be auto-fixed?
    fix_action: FixAction | None  # structured fix instruction
```

The fixer module (`src/dco/fixer.py`) collects all `FixAction` objects, sorts by line number **bottom-to-top** (so earlier fixes don't shift line numbers of later ones), and applies replacements to the Dockerfile content string. Uses `dockerfile-parse`'s `dfp.baseimage` setter for FROM changes and string manipulation for RUN changes.

**Auto-fix capability per rule:**

| Rule | Auto-fixable? | How |
|------|--------------|-----|
| DCO001 | Yes | `dfp.baseimage = "image:tag-slim"` |
| DCO002 | Yes | Join consecutive RUN values with ` && \`, write as single RUN |
| DCO003 | Yes | Append `&& apt-get purge -y <pkg> && apt-get autoremove -y` to the RUN |
| DCO004 | Yes | Generate `.dockerignore` file from language-specific template |
| DCO005 | No (suggest only) | Too complex - requires restructuring entire Dockerfile into build/runtime stages |
| DCO006 | Yes | Query Docker Hub for latest stable tag, replace in FROM line |

### Carbon Estimation Formula

```
CO2_per_month = size_saved_GB * pulls_per_month * network_kWh_per_GB * grid_gCO2_per_kWh / 1000
```

- `network_kWh_per_GB`: Aslan et al. 2018 baseline of 0.06 kWh/GB (2015), halving every 2 years
- `pulls_per_month`: Docker Hub API (`pull_count / months_since_registration`) or CLI override (default: 100,000)
- `grid_gCO2_per_kWh`: world average ~436 gCO2/kWh (IEA 2023), configurable per region

### CLI Commands

```
dco analyze <Dockerfile> [OPTIONS]    # Analyze single file, output table
dco fix <Dockerfile> [OPTIONS]        # Generate an optimized Dockerfile
dco batch <directory>                 # Analyze all Dockerfiles in directory
dco info <image>                      # Show Docker Hub stats for an image

Analyze/Fix shared options:
  --pulls-per-month INTEGER   Override pull frequency [default: 100000]
  --region TEXT                Grid region for carbon intensity [default: "world"]
  --format TEXT                Output format: table, json, csv [default: table]
  --no-dockerhub              Skip Docker Hub API calls
  --measure-build             Actually build images and measure energy (slow)
  --output FILE               Write results to file

Fix-specific options:
  --in-place                  Overwrite the original Dockerfile (asks for confirmation)
  --output-path PATH          Write optimized file to custom path [default: Dockerfile.optimized]
  --rules TEXT                Comma-separated rule IDs to fix (e.g., "DCO001,DCO002") [default: all auto-fixable]
  --dry-run                   Show what would change without writing any files
```

### Six Detection Rules

| ID | Rule | What it detects | Example size saving |
|----|------|-----------------|---------------------|
| DCO001 | Oversized base image | `python:3.12` when `python:3.12-slim` exists | ~855 MB |
| DCO002 | Uncombined RUN layers | 4 consecutive `RUN apt-get install` commands | ~120 MB |
| DCO003 | Dev deps in production | `gcc`, `build-essential` left installed | ~200 MB |
| DCO004 | Missing .dockerignore | No `.dockerignore` file in build context | ~50-500 MB |
| DCO005 | Missing multi-stage build | Go/Rust/Java build without multi-stage | ~400-800 MB |
| DCO006 | Unpinned base image tag | `FROM python` or `FROM python:latest` | Variable |

---

## Team Allocation (5 Members, Equal Division)

### Member 1: Core Infrastructure + Fix Engine (Critical Path)

**Deliverables (15 files):**
- `pyproject.toml` - project config, dependencies, entry point
- `src/dco/__init__.py` - package init
- `src/dco/cli.py` - Typer app with analyze/fix/batch/info commands
- `src/dco/parser.py` - Dockerfile parsing wrapper around dockerfile-parse
- `src/dco/rules/__init__.py` - Rule protocol, Finding dataclass, FixAction dataclass, rule registry
- `src/dco/fixer.py` - Auto-fix engine: collects FixActions, applies bottom-to-top, writes output
- `src/dco/output.py` - Rich table formatter for findings + before/after diff display
- `src/dco/config.py` - Constants, defaults, settings
- `src/dco/carbon/__init__.py` - carbon package init
- `tests/conftest.py` - Shared test fixtures
- `tests/test_parser.py` - Parser tests
- `tests/test_fixer.py` - Fixer engine tests (apply single fix, apply multiple fixes, line offset handling)
- `tests/test_cli.py` - CLI integration tests (including `dco fix` command)
- `tests/fixtures/*.Dockerfile` - 5-6 sample Dockerfiles for testing
- Integration: wire all modules together end-to-end

**Timeline:**
- Days 1-2: pyproject.toml, parser.py, Rule protocol + FixAction, CLI skeleton (MUST deliver by day 2)
- Days 3-4: output.py (Rich tables), wire rules into CLI, config.py
- Days 5-7: fixer.py engine, `dco fix` command, integration testing
- Days 8-14: Batch command, --format json/csv, --dry-run, --in-place, final packaging

**Effort:** ~42 hours (high complexity, critical path, fixer adds ~5 hours)

---

### Member 2: Base Image & Pinning Rules + Image Data + Their Auto-Fixes

**Deliverables (13 files):**
- `src/dco/rules/base_image.py` - DCO001: detect oversized base images + return FixAction (replace FROM line)
- `src/dco/rules/pinning.py` - DCO006: detect unpinned tags + return FixAction (pin to latest stable tag)
- `src/dco/data/image_sizes.json` - mapping of 20+ base images to sizes, slim alternatives, and latest pinned tags
- `scripts/collect_image_sizes.py` - script to query Docker Hub for image sizes and tags
- `tests/test_rules/test_base_image.py` - unit tests including auto-fix output verification
- `tests/test_rules/test_pinning.py` - unit tests including auto-fix output verification
- `tests/fixtures/oversized_python.Dockerfile` - test fixture
- `tests/fixtures/slim_python.Dockerfile` - test fixture (should not trigger)
- `tests/fixtures/unpinned_tag.Dockerfile` - test fixture
- `tests/fixtures/pinned_tag.Dockerfile` - test fixture (should not trigger)
- `tests/fixtures/expected_fixed_base_image.Dockerfile` - expected output after DCO001 fix
- Documentation: rule descriptions in README (DCO001, DCO006 sections)
- Video: record demo segment for presentation

**Timeline:**
- Days 1-2: Research Docker Hub tags API, start collecting image sizes for top 20 images
- Days 3-4: base_image.py rule + FixAction generation + tests
- Days 5-7: pinning.py rule + FixAction generation + tests, finalize image_sizes.json with pinned tags
- Days 8-9: Help run validation, verify auto-fixes produce valid Dockerfiles
- Days 10-14: README rule documentation, review paper, record video segment

**Effort:** ~40 hours (medium complexity, data collection intensive, +2 hours for fix logic)

---

### Member 3: Pattern-Matching Rules (4 rules) + Their Auto-Fixes

**Deliverables (16 files):**
- `src/dco/rules/run_layers.py` - DCO002: uncombined RUN layers + FixAction (combine with &&)
- `src/dco/rules/dev_deps.py` - DCO003: dev dependencies in production + FixAction (append purge command)
- `src/dco/rules/dockerignore.py` - DCO004: missing .dockerignore + FixAction (generate file from template)
- `src/dco/rules/multistage.py` - DCO005: missing multi-stage builds (analysis only, no auto-fix)
- `src/dco/fixer_templates.py` - .dockerignore templates per language (Python, Node, Go, Java, default)
- `src/dco/data/dev_packages.json` - list of known dev dependency packages
- `tests/test_rules/test_run_layers.py` - unit tests including fix output verification
- `tests/test_rules/test_dev_deps.py` - unit tests including fix output verification
- `tests/test_rules/test_dockerignore.py` - unit tests including fix output verification
- `tests/test_rules/test_multistage.py` - unit tests
- `tests/fixtures/uncombined_runs.Dockerfile` - test fixture
- `tests/fixtures/expected_fixed_runs.Dockerfile` - expected output after DCO002 fix
- `tests/fixtures/dev_deps_left.Dockerfile` - test fixture
- `tests/fixtures/no_multistage_go.Dockerfile` - test fixture
- `tests/fixtures/clean_multistage.Dockerfile` - test fixture (should not trigger)
- Documentation: rule descriptions in README (DCO002-DCO005 sections)

**Timeline:**
- Days 1-2: Research dev package names, build dev_packages.json, study Dockerfile patterns
- Days 3-4: run_layers.py + FixAction (combine RUNs) + dev_deps.py + FixAction (append purge) + tests
- Days 5-7: dockerignore.py + fixer_templates.py + multistage.py (suggest-only) + tests
- Days 8-9: Help run validation, verify auto-fixes produce valid Dockerfiles
- Days 10-14: README usage examples, review paper, record video segment

**Effort:** ~42 hours (4 rules, 3 with auto-fix logic, +4 hours for fix generation and templates)

---

### Member 4: Carbon Estimation Model + Docker Hub API + Energy Measurement

**Deliverables (13 files):**
- `src/dco/carbon/network.py` - Aslan et al. network energy model
- `src/dco/carbon/pull_frequency.py` - Docker Hub API client
- `src/dco/carbon/build.py` - CodeCarbon/EnergiBridge measurement wrapper
- `src/dco/carbon/model.py` - combine all dimensions into CO2 estimate
- `src/dco/data/grid_intensity.json` - IEA grid carbon intensity by country/region
- `tests/test_carbon/test_network.py` - unit tests for network model
- `tests/test_carbon/test_pull_frequency.py` - unit tests with mocked Docker Hub API
- `tests/test_carbon/test_model.py` - unit tests for combined model
- `tests/test_carbon/test_build.py` - unit tests for energy measurement
- Documentation: carbon model explanation in README
- Sensitivity analysis script for the paper
- Energy measurement experiment runner (before/after builds)
- Results visualization (charts for paper)

**Timeline:**
- Days 1-2: Implement Aslan et al. formula in network.py, start grid_intensity.json
- Days 3-4: pull_frequency.py (Docker Hub client) + tests with mocked responses
- Days 5-7: model.py (combine dimensions), complete grid_intensity.json
- Days 8-9: build.py (CodeCarbon integration), test on real Docker builds
- Days 10-11: Sensitivity analysis on carbon model parameters (vary energy intensity, grid factor, pull count)
- Days 12-14: Review paper, contribute carbon model section, record video segment

**Effort:** ~40 hours (high complexity, research-heavy)

---

### Member 5: Validation + Paper + CI/CD + README

**Deliverables (12+ files):**
- `validation/collect_dockerfiles.py` - script to fetch Dockerfiles from top GitHub repos
- `validation/run_validation.py` - batch analysis runner, outputs CSV
- `validation/dockerfiles/` - 30-50 real Dockerfiles from popular OSS repos
- `validation/results/` - CSV/JSON output from validation runs
- `.github/workflows/ci.yml` - CI pipeline (Ruff + pytest + coverage)
- `README.md` - installation, usage, examples, contributing guide
- `LICENSE` - MIT license
- Paper (4-10 pages, IEEE format):
  - Section 1: Introduction + motivation
  - Section 2: Related work (hadolint, dockle, CO2.js)
  - Section 3: Approach (rule system + carbon model)
  - Section 4: Validation results
  - Section 5: Discussion + threats to validity
  - Section 6: Conclusion
- 3-minute video presentation

**Timeline:**
- Days 1-2: Set up CI/CD pipeline, start collecting Dockerfiles from GitHub
- Days 3-4: Collect 30-50 Dockerfiles, paper outline + sections 1-2
- Days 5-7: Draft paper sections 3 (approach)
- Days 8-9: Run validation on all collected Dockerfiles using the tool
- Days 10-11: Paper sections 4-5 (results, discussion), aggregate statistics
- Days 12-14: Finalize paper, compile video, README, submit deliverables

**Effort:** ~40 hours (writing-heavy, coordination role)

---

## Workload Summary

| Member | Code Files | Test Files | Other | Total Items | Complexity |
|--------|-----------|------------|-------|-------------|------------|
| 1 (Core + Fixer) | 8 (incl. fixer.py) | 4+fixtures | pyproject.toml, integration | 15 | High |
| 2 (Base Image) | 2+data | 2+fixtures | script, docs, video, expected-fix fixtures | 13 | Medium |
| 3 (Patterns) | 5 (incl. fixer_templates.py) | 4+fixtures | docs, expected-fix fixtures | 16 | Medium-High |
| 4 (Carbon) | 4+data | 4 | sensitivity, visualization | 13 | High |
| 5 (Validation) | 2+data | 0 | CI, README, paper, video, fix validation | 12+ | Writing-heavy |

All members contribute roughly equal effort (~40-42 hours each).

---

## Sprint Timeline

### Sprint 1 (Days 1-7): Foundation

| Day | Member 1 | Member 2 | Member 3 | Member 4 | Member 5 |
|-----|----------|----------|----------|----------|----------|
| 1-2 | pyproject.toml, parser.py, Rule protocol + FixAction, CLI skeleton | Collect image sizes from Docker Hub tags API | Research dev packages, build dev_packages.json | Implement Aslan et al. formula in network.py | Set up CI/CD, start collecting Dockerfiles |
| 3-4 | output.py, wire rules into CLI | base_image.py + fix logic + tests | run_layers.py + fix logic + dev_deps.py + fix logic + tests | pull_frequency.py + tests | Collect 30-50 Dockerfiles, paper outline |
| 5-7 | fixer.py engine, `dco fix` command, integration testing | pinning.py + fix logic + tests | dockerignore.py + fixer_templates.py + multistage.py + tests | model.py, grid_intensity.json | Draft paper sections 1-3 |

**Sprint 1 Milestone:** All 6 rules implemented and tested. CLI outputs findings table with CO2 estimates. CI pipeline green.

### Sprint 2 (Days 8-14): Integration + Validation + Polish

| Day | Member 1 | Member 2 | Member 3 | Member 4 | Member 5 |
|-----|----------|----------|----------|----------|----------|
| 8-9 | Batch command, --dry-run, --in-place | Help validation, verify fixes build correctly | Help validation, verify fixes build correctly | CodeCarbon build measurement | Run validation on 30-50 files (analyze + fix) |
| 10-11 | Final CLI polish, --format options | README: rule + fix docs | README: usage examples incl. fix | Sensitivity analysis | Paper sections 4-5 (include fix results) |
| 12-14 | Release prep, pip packaging | Review paper, video | Review paper, video | Review paper, video | Finalize paper + video |

**Sprint 2 Milestone:** Validation complete. Paper written. Tool packaged. Video recorded.

---

## Git Workflow

- **Main branch:** always releasable
- **Feature branches:** `feat/rule-base-image`, `feat/carbon-model`, `feat/cli-skeleton`, etc.
- **PR process:** 1 approval required, squash-merge
- **Branch naming:** `feat/`, `fix/`, `docs/`, `test/` prefixes

---

## Dependencies (pyproject.toml)

```toml
[project]
name = "dockerfile-carbon-optimizer"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.9.0",
    "rich>=13.0.0",
    "dockerfile-parse>=2.0.0",
    "httpx>=0.25.0",
]

[project.optional-dependencies]
energy = ["codecarbon>=2.3.0"]
docker = ["docker>=7.0.0"]
dev = ["pytest>=7.0.0", "pytest-cov>=4.0.0", "respx>=0.20.0", "ruff>=0.3.0"]

[project.scripts]
dco = "dco.cli:app"
```

---

## Risks and Mitigations

| Risk | Probability | Mitigation |
|------|-------------|------------|
| Tight 2-week timeline | High | MVP = 3-4 rules + carbon table. Multistage and dockerignore are stretch goals |
| Energy measurement variance between runs | Medium | Run each build 5x, report median with confidence intervals, document hardware |
| Aslan et al. extrapolation to 2026 gives tiny numbers | Certain | Report as ranges (pessimistic to optimistic), document all parameters and formula |
| Docker Hub API rate limits | Low | Generous for reads (thousands/min); cache results; accept --pulls-per-month override |
| Cross-platform Docker differences | Medium | Core analysis is pure Python (no Docker needed). Only --measure-build requires Docker |
| Base image size data goes stale | Medium | Ship static JSON + add `dco update-data` command to refresh from Docker Hub |
| dockerfile-parse library is unmaintained | Low | Simple library, works fine for our needs. Fallback: regex-based parsing |
| Auto-fix generates invalid Dockerfile | Medium | Validate fixed Dockerfile syntax before writing. Run `docker build --check` or re-parse with dockerfile-parse. Include --dry-run flag to preview changes |
| Auto-fix breaks user's Dockerfile | Medium | Never overwrite original by default (write to Dockerfile.optimized). --in-place requires explicit confirmation. DCO005 (multi-stage) is suggest-only, not auto-fixed |

---

## Test Case Zero: The Course's Own Dockerfile

The course repository's own `Dockerfile` is a perfect demo:

```dockerfile
FROM ruby:3.2              # DCO001: ruby:3.2-slim saves ~600MB
                           # DCO006: Unpinned patch version
COPY . /myapp              # DCO004: .git directory in build context
RUN gem install bundler    # DCO002: 3 separate RUN gem installs
RUN gem install jekyll     #   could be one combined RUN
RUN bundle install
```

Running `dco fix` on this Dockerfile would produce an optimized version:

```dockerfile
FROM ruby:3.2-slim           # DCO001 fixed: switched to slim variant
WORKDIR /myapp
COPY . /myapp

RUN gem install rubygems-update -v 3.4.1 && \
    update_rubygems && \
    gem install bundler -v 2.7.2 && \
    gem install jekyll -v 3.9.3 && \
    bundle install            # DCO002 fixed: combined into single RUN

EXPOSE 4000
CMD ["bundle", "exec", "jekyll", "serve", "--host", "0.0.0.0", "--safe"]
```

Plus a generated `.dockerignore` (DCO004 fix). Use both the before and after in the paper and video.
