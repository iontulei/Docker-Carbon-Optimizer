# Dockerfile Carbon Optimizer (DCO)

A CLI tool that analyzes Dockerfiles for energy-wasteful patterns and estimates the carbon cost of inefficient container images.

## Installation

Requires Python 3.10+.

```bash
python -m venv .venv
.venv/Scripts/activate           # Windows
# or: source .venv/bin/activate  # Linux/macOS
pip install -e ".[dev]"
```

Dependencies are organized into groups so users only install what they need:

| Install command | What it includes |
|---|---|
| `pip install -e .` | Core tool only (typer, rich, dockerfile-parse, httpx) |
| `pip install -e ".[dev]"` | + testing and linting (pytest, ruff) |
| `pip install -e ".[energy]"` | + CodeCarbon for measuring real build energy (kWh) |
| `pip install -e ".[dev,energy]"` | Everything (recommended for development) |

## Usage

### Analyze a Dockerfile

```bash
dco analyze Dockerfile
```

Options:
- `--format table|json|csv` - output format (default: table)
- `--region REGION` - electricity grid region for CO2 calculation (default: world). See [Carbon Estimation Model](#carbon-estimation-model) for all region codes.
- `--pulls-per-month N` - manually set the monthly pull count used in CO2 calculation. If omitted, the real pull count is fetched from Docker Hub automatically.
- `--no-dockerhub` - disable all Docker Hub API calls. When set, and `--pulls-per-month` is not provided, a default of 100,000 pulls/month is used.
- `--output FILE` - write results to a file instead of printing to the terminal

**How pull count is determined:**
1. If you pass `--pulls-per-month N`, that value is always used.
2. Otherwise, DCO calls Docker Hub to get the real pull count for the base image.
3. If `--no-dockerhub` is set (or the API call fails), it falls back to 100,000.

Examples:
```bash
# Default: fetches real pull count from Docker Hub
dco analyze Dockerfile

# Manually set pull count (skips Docker Hub automatically)
dco analyze Dockerfile --pulls-per-month 5000

# Offline mode: no API calls, uses 100k default
dco analyze Dockerfile --no-dockerhub

# Use France's low-carbon grid
dco analyze Dockerfile --region fr

# Compare CO2 across regions
dco analyze Dockerfile --region cn
dco analyze Dockerfile --region no

# JSON output
dco analyze Dockerfile --format json

# Save CSV results to a file
dco analyze Dockerfile --format csv --output results.csv
```

### Fix a Dockerfile

```bash
dco fix Dockerfile
```

The fix command first runs analysis to detect issues, then applies fixes. It does not display CO2 estimates, so `--region`, `--pulls-per-month`, and `--no-dockerhub` are not needed here.

Options:
- `--dry-run` - show the diff of what would change without writing any files
- `--in-place` - overwrite the original file (asks for confirmation)
- `--output FILE` - write optimized Dockerfile to a specific path (default: `Dockerfile.optimized`)
- `--rules DCO001,DCO002` - only apply fixes for the listed rule IDs
- `--force` - also apply fixes marked as unsafe (currently DCO001 base image swap). By default, DCO001 is detect-only because switching to a slim image can break apps that depend on build tools.

Examples:
```bash
# Preview all safe fixes (shows diff, writes nothing)
dco fix Dockerfile --dry-run

# Apply all safe fixes (writes to Dockerfile.optimized)
dco fix Dockerfile

# Preview ALL fixes including unsafe base image swap
dco fix Dockerfile --force --dry-run

# Apply only RUN-combining and dev-deps cleanup
dco fix Dockerfile --rules DCO002,DCO003

# Overwrite the original file (asks confirmation)
dco fix Dockerfile --in-place

# Write to a custom output path
dco fix Dockerfile --output optimized/Dockerfile
```

### Batch analysis

```bash
dco batch ./project-dir
```

Scans a directory for all Dockerfiles (`*Dockerfile*` and `*.dockerfile`) and analyzes each one. Prints per-file results and a batch summary.

Examples:
```bash
# Scan all fixtures
dco batch tests/fixtures/

# Batch with JSON output
dco batch ./my-services/ --format json

# Batch without Docker Hub calls (faster)
dco batch ./my-services/ --no-dockerhub

# Batch with a specific region
dco batch ./my-services/ --region eu
```

### Image info

```bash
dco info python:3.12
```

Queries Docker Hub for an image and shows pull count, stars, and description.

Examples:
```bash
dco info python:3.12
dco info nginx
dco info golang:1.21
```

## Detection Rules

These 6 rules target the most impactful Dockerfile anti-patterns for image size and build efficiency. They were selected based on:

- **Measurable impact** - each rule targets a pattern that produces a quantifiable size or layer reduction, enabling CO2 estimation
- **Prevalence in practice** - these are the most common inefficiencies found in real-world Dockerfiles (based on Docker best practices documentation and academic literature on container optimization)
- **Fixability** - most rules can be auto-fixed without breaking the build, making the tool actionable rather than just advisory
- **Coverage** - together they address all layers of Dockerfile optimization: base image selection (DCO001, DCO005, DCO006), build instructions (DCO002, DCO003), and build context (DCO004)

| Rule   | Name                    | Severity | Auto-fix       |
|--------|-------------------------|----------|----------------|
| DCO001 | Oversized Base Image    | High     | `--force` only |
| DCO002 | Uncombined RUN Layers   | Medium   | Yes            |
| DCO003 | Dev Deps in Production  | High     | Yes            |
| DCO004 | Missing .dockerignore   | Low      | Yes            |
| DCO005 | Missing Multi-stage     | Medium   | No             |
| DCO006 | Unpinned Base Image Tag | Low      | Yes            |

---

### DCO001 - Oversized Base Image

Detects base images that have smaller slim or alpine alternatives. For example, `python:3.12` is ~392 MB while `python:3.12-slim` is ~41 MB.

**Not auto-fixable by default.** Slim images remove build tools (`gcc`, `build-essential`, dev headers). If your app compiles C extensions (numpy, psycopg2) or shells out to utilities (`curl`, `git`), switching to slim may break it. Use `--force` only after verifying your app has no native dependencies.

**Before:**
```dockerfile
FROM python:3.12
RUN pip install flask
COPY . /app
CMD ["python", "app.py"]
```

**After (`dco fix --force`):**
```dockerfile
FROM python:3.12-slim
RUN pip install flask
COPY . /app
CMD ["python", "app.py"]
```

Examples:
```bash
# Detect oversized images
dco analyze Dockerfile

# Preview the base image swap without applying
dco fix Dockerfile --force --dry-run

# Apply the swap (writes to Dockerfile.optimized)
dco fix Dockerfile --force
```

---

### DCO002 - Uncombined RUN Layers

Detects 2+ consecutive `RUN` instructions that create unnecessary image layers. Each extra layer adds overhead ranging from KB to MB, depending on what the command does (e.g. package manager caches stored in one layer cannot be removed by a later layer).

**Before:**
```dockerfile
RUN apt-get update
RUN apt-get install -y curl
RUN pip install flask gunicorn
```

**After (`dco fix`):**
```dockerfile
RUN apt-get update && \
    apt-get install -y curl && \
    pip install flask gunicorn
```

Examples:
```bash
# Detect uncombined RUN layers
dco analyze tests/fixtures/uncombined_runs.Dockerfile

# Preview the combined output
dco fix tests/fixtures/uncombined_runs.Dockerfile --dry-run

# Apply only this rule
dco fix Dockerfile --rules DCO002
```

---

### DCO003 - Dev Deps in Production

Detects development/build packages (`gcc`, `build-essential`, `python3-dev`, etc.) left in the final image. The size impact is calculated per package using approximate installed sizes (e.g. `gcc` ~50 MB, `build-essential` ~250 MB). Supports both `apt-get` (Debian/Ubuntu) and `apk` (Alpine) package managers.

If the Dockerfile uses multi-stage builds, only the final stage is checked (dev deps in a builder stage are fine).

**Before:**
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y gcc build-essential python3-dev
RUN pip install numpy pandas
```

**After (`dco fix`):**
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y gcc build-essential python3-dev && \
    apt-get purge -y gcc build-essential python3-dev && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN pip install numpy pandas
```

Examples:
```bash
# Detect dev deps left in production
dco analyze tests/fixtures/dev_deps_left.Dockerfile

# Preview the cleanup fix
dco fix tests/fixtures/dev_deps_left.Dockerfile --dry-run

# Apply only this rule
dco fix Dockerfile --rules DCO003
```

---

### DCO004 - Missing .dockerignore

Detects when no `.dockerignore` file exists in the build context. Without one, the entire directory (including `.git`, `node_modules`, `.venv`) is sent to the Docker daemon. DCO scans the directory and reports the actual size of excludable files found.

The fix generates a language-specific `.dockerignore` template (Python, Node, Go, Java, or a sensible default) based on files detected in the project directory.

**Note:** This fix generates a separate `.dockerignore` file rather than modifying the Dockerfile. It will not appear in `--dry-run` output since there is no Dockerfile diff.

Examples:
```bash
# Detect missing .dockerignore
dco analyze Dockerfile

# Apply all fixes (generates .dockerignore alongside the optimized Dockerfile)
dco fix Dockerfile

# Apply only this rule
dco fix Dockerfile --rules DCO004
```

---

### DCO005 - Missing Multi-stage Build

Detects compiled-language images (`golang`, `rust`, `maven`, `openjdk`, `gradle`) that use a single-stage build with a compile command. Build tools and source code remain in the final image. DCO looks up the base image size from Docker Hub data and estimates savings by subtracting a minimal runtime baseline (~5 MB, typical for Alpine/distroless).

**Not auto-fixable** -restructuring a Dockerfile into builder/runtime stages requires manual review. DCO provides a suggestion instead.

**Example triggering Dockerfile:**
```dockerfile
FROM golang:1.21
WORKDIR /app
COPY . .
RUN go build -o server .
CMD ["./server"]
```

**Suggested fix (manual):**
```dockerfile
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o server .

FROM gcr.io/distroless/base
COPY --from=builder /app/server /server
CMD ["/server"]
```

Examples:
```bash
# Detect missing multi-stage build
dco analyze tests/fixtures/no_multistage_go.Dockerfile

# Verify a proper multi-stage build passes cleanly
dco analyze tests/fixtures/clean_multistage.Dockerfile

# Batch scan to find all single-stage compiled builds
dco batch ./my-go-services/
```

---

### DCO006 - Unpinned Base Image Tag

Detects base images using unpinned tags like `:latest`, no tag at all, or major-only tags (e.g., `python:3`). Unpinned tags cause non-reproducible builds -the image content can change without warning.

Tags considered pinned: minor versions (`3.12`), patch versions (`3.12.13`), variant tags (`3.12-slim`), codenames (`bookworm`), and digest references (`@sha256:...`).

**Before:**
```dockerfile
FROM python
RUN pip install flask
```

**After (`dco fix`):**
```dockerfile
FROM python:3.13.3
RUN pip install flask
```

Examples:
```bash
# Detect unpinned tags
dco analyze tests/fixtures/unpinned_tag.Dockerfile

# Preview the pinned version
dco fix tests/fixtures/unpinned_tag.Dockerfile --dry-run

# Verify a properly pinned image passes
dco analyze tests/fixtures/pinned_tag.Dockerfile
```

---

## Carbon Estimation Model

DCO estimates the monthly CO2 savings from reducing Docker image size. Every time a Docker image is pulled, the size difference is transferred over the network, consuming energy. Multiply that by thousands of pulls per month and it adds up.

**Formula:**

```
CO2 (g/month) = size_saved_GB * pulls_per_month * network_kWh_per_GB * grid_gCO2_per_kWh
```

- **`size_saved_GB`** -estimated by each rule (e.g. DCO001 knows python:3.12 is 392 MB vs slim at 41 MB)
- **`pulls_per_month`** -how often the image is pulled. Set with `--pulls-per-month N`, otherwise fetched from Docker Hub automatically, or defaults to 100,000 when offline (`--no-dockerhub`).
- **`network_kWh_per_GB`** -follows Aslan et al. (2018): baseline 0.06 kWh/GB in 2015, halving every 2 years
- **`grid_gCO2_per_kWh`** -carbon intensity of electricity in the selected region. Uses IEA Emissions Factors 2024/2025 and Ember Global Electricity Review 2024 data. Set with `--region`.

**Available regions** (`--region` flag):

| Code | Region          | gCO2/kWh |
|------|-----------------|-----------|
| world | World Average  | 445       |
| us    | United States  | 369       |
| eu    | European Union | 199       |
| uk    | United Kingdom | 125       |
| fr    | France         | 22        |
| de    | Germany        | 321       |
| cn    | China          | 581       |
| in    | India          | 708       |
| au    | Australia      | 466       |
| jp    | Japan          | 482       |
| kr    | South Korea    | 396       |
| ca    | Canada         | 136       |
| br    | Brazil         | 109       |
| se    | Sweden         | 41        |
| no    | Norway         | 27        |
| pl    | Poland         | 666       |

**Example:** Saving 350 MB on an image pulled 100,000 times/month:
- World average: ~20,700 g CO2/month
- France (nuclear): ~1,020 g CO2/month
- China (coal): ~27,000 g CO2/month

```bash
# Compare the same Dockerfile across different grids
dco analyze Dockerfile --no-dockerhub --region world
dco analyze Dockerfile --no-dockerhub --region fr
dco analyze Dockerfile --no-dockerhub --region cn

# See how pull count affects the estimate
dco analyze Dockerfile --no-dockerhub --pulls-per-month 100
dco analyze Dockerfile --no-dockerhub --pulls-per-month 1000000
```

## Dependencies

DCO is built on the following external packages:

### Core dependencies

| Package | Purpose |
|---|---|
| [Typer](https://typer.tiangolo.com/) | CLI framework - command parsing, help text, argument validation |
| [Rich](https://rich.readthedocs.io/) | Terminal output - colored tables, progress bars, formatted text |
| [dockerfile-parse](https://github.com/containerbuildsystem/dockerfile-parse) | Dockerfile parsing - extracts FROM, RUN, COPY instructions into structured data |
| [httpx](https://www.python-httpx.org/) | HTTP client - Docker Hub API calls for pull counts and image info |

### Optional dependencies

| Package | Group | Purpose |
|---|---|---|
| [CodeCarbon](https://codecarbon.io/) | `energy` | Energy measurement - wraps Intel RAPL (Linux) or powermetrics (macOS) to measure kWh during Docker builds |
| [pytest](https://docs.pytest.org/) | `dev` | Test framework |
| [ruff](https://docs.astral.sh/ruff/) | `dev` | Linter and formatter |
| [respx](https://lundberg.github.io/respx/) | `dev` | Mock HTTP responses for testing Docker Hub API calls |

## Data Collection

DCO uses `image_sizes.json` to look up base image sizes and their slim/alpine alternatives. This file is generated by querying the Docker Hub API:

```bash
python scripts/collect_image_sizes.py          # Default: top 100 most-pulled images
python scripts/collect_image_sizes.py --top 50  # Fewer images (faster)
```

The script (`scripts/collect_image_sizes.py`) discovers the most-pulled images on Docker Hub, queries each image's tags for compressed sizes, and records slim/alpine variants with their sizes. Output is written to `src/dco/data/image_sizes.json`.

You only need to re-run this if you want to update the image size data (e.g., after new image versions are released). The checked-in `image_sizes.json` is sufficient for normal use.

## Validation

The validation pipeline tests DCO against 10 real GitHub repos with intentionally un-optimized Dockerfiles. It measures image size, build time, energy consumption, and CO2 emissions before and after optimization.

### Prerequisites

- Python 3.10+ with a virtual environment
- `pip install -e ".[dev,energy]"` (the `energy` group installs CodeCarbon)
- Docker Desktop installed and running
- `sudo` access on macOS (CodeCarbon uses `powermetrics` to read CPU power)
- Internet access (for cloning repos and pulling base images)

### How it works

1. `repos.json` lists 10 repos across 5 languages (Python, Node, Java, Go, PHP)
2. The script clones each repo, then copies an un-optimized Dockerfile from `validation/dockerfiles/<name>/` over the original
3. For repos flagged with `delete_dockerignore`, the `.dockerignore` is temporarily removed (to trigger DCO004)
4. `dco analyze` detects issues, then `dco fix --force` applies all fixes
5. Docker cache is fully pruned (`docker system prune -a -f`) before each build
6. Both BEFORE (un-optimized) and AFTER (optimized) images are built with `--no-cache --pull`
7. CodeCarbon measures energy (kWh) and CO2 (g) during each build
8. Image sizes (MB) and build times (s) are recorded
9. Original Dockerfile and `.dockerignore` are restored after each repo
10. Results are written to `validation/results/results.csv`

### Running validation

```bash
cd sustainable-implementation
python -m venv .venv
source .venv/bin/activate              # Linux/macOS
# or: .venv/Scripts/activate           # Windows

pip install -e ".[dev,energy]"

# Linux / Windows
python validation/run_validation.py

# macOS (sudo needed for CodeCarbon energy measurement)
sudo .venv/bin/python3 validation/run_validation.py
```

Estimated runtime: 1.5-3 hours for all 10 repos (each repo builds twice from scratch).

### Test repos

| Repo | Language | Rules triggered |
|---|---|---|
| gitea | Go | DCO001, DCO002, DCO004, DCO005, DCO006 |
| flask-sample-app | Python | DCO001, DCO002, DCO003 |
| docker-curriculum | Python | DCO001, DCO006 |
| spring-boot-hello | Java | DCO002, DCO004, DCO005, DCO006 |
| getting-started-todo-app | Node | DCO002, DCO004, DCO006 |
| etherpad | Node | DCO002, DCO006 |
| umami | Node | DCO001, DCO002, DCO003 |
| outline | Node | DCO002, DCO006 |
| directus | Node | DCO001, DCO002, DCO003 |
| appwrite | PHP | DCO002, DCO004, DCO006 |

All 6 rules appear at least twice across the test set. Gitea triggers the most rules (5) as a single-stage Go build.

## Development

### Run tests

```bash
pytest tests/ -v
```

### Run tests with coverage

```bash
pytest tests/ --cov=dco --cov-report=term-missing
```

### Lint

```bash
ruff check src/ tests/
```

## Project Structure

```
sustainable-implementation/
├── pyproject.toml                  # Project config, dependencies, entry point
├── scripts/
│   └── collect_image_sizes.py      # Docker Hub image size collector
├── docs/
│   ├── research.md                 # Research references and background
│   ├── raw-impl-plan.md            # Implementation plan
│   └── raw-test-plan.md            # Testing strategy
├── src/dco/
│   ├── __init__.py                 # Package init, version
│   ├── cli.py                      # Typer CLI (analyze, fix, batch, info)
│   ├── parser.py                   # Dockerfile parsing wrapper
│   ├── config.py                   # Constants and defaults
│   ├── output.py                   # Rich table, JSON, CSV formatting
│   ├── fixer.py                    # Auto-fix engine (bottom-to-top)
│   ├── fixer_templates.py          # .dockerignore templates per language
│   ├── rules/
│   │   ├── __init__.py             # Rule protocol, Finding/FixAction, registry
│   │   ├── _utils.py               # Shared utilities (parse_from_value)
│   │   ├── base_image.py           # DCO001: Oversized base image
│   │   ├── run_layers.py           # DCO002: Uncombined RUN layers
│   │   ├── dev_deps.py             # DCO003: Dev dependencies in production
│   │   ├── dockerignore.py         # DCO004: Missing .dockerignore
│   │   ├── multistage.py           # DCO005: Missing multi-stage build
│   │   └── pinning.py              # DCO006: Unpinned base image tag
│   ├── carbon/
│   │   ├── __init__.py             # Carbon package exports
│   │   ├── estimator.py            # Aslan et al. model + CarbonEstimator
│   │   ├── pull_frequency.py       # Docker Hub API client (pull counts)
│   │   └── build.py                # CodeCarbon energy measurement wrapper
│   └── data/
│       ├── __init__.py             # Data loading utilities
│       ├── image_sizes.json        # Base image sizes, slim/alpine variants
│       ├── dev_packages.json       # Known dev/build package names
│       └── grid_intensity.json     # Grid carbon intensity by region
├── tests/
│   ├── conftest.py                 # Shared test fixtures
│   ├── test_parser.py              # Parser tests
│   ├── test_fixer.py               # Fixer tests
│   ├── test_cli.py                 # CLI integration tests
│   ├── test_carbon/
│   │   ├── test_estimator.py       # Carbon estimator tests
│   │   ├── test_pull_frequency.py  # Docker Hub API tests (mocked)
│   │   └── test_build.py           # Build energy tracker tests
│   ├── test_rules/
│   │   ├── test_base_image.py      # DCO001 tests
│   │   ├── test_run_layers.py      # DCO002 tests
│   │   ├── test_dev_deps.py        # DCO003 tests
│   │   ├── test_dockerignore.py    # DCO004 tests
│   │   ├── test_multistage.py      # DCO005 tests
│   │   └── test_pinning.py         # DCO006 tests
│   └── fixtures/                   # Sample Dockerfiles for testing
└── validation/
    ├── repos.json                  # 10 test repos with metadata
    ├── collect_dockerfiles.py      # Clone repos from repos.json
    ├── run_validation.py           # Full pipeline: analyze, fix, build, measure
    ├── dockerfiles/                # Un-optimized Dockerfiles (one per repo)
    └── results/
        └── results.csv             # Output: size, time, energy, CO2 per repo
```
