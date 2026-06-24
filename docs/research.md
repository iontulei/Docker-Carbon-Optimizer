# Dockerfile Carbon Optimizer - Research & References

This document collects the research, tools, concepts, and links needed to implement the Dockerfile Carbon Optimizer project.

---

## 1. What is a CLI (Command-Line Interface)?

A CLI is a program that accepts text input from a terminal to execute commands. Instead of a graphical UI, users interact by typing commands like `dco analyze Dockerfile`.

**Why build a CLI for this project?** CLIs are the standard way to integrate developer tools into workflows. Dockerfile linting happens at build time, in CI/CD pipelines, and in terminals - all command-line environments.

### How to Build a CLI in Python

There are three main approaches:

**argparse (built-in):**
- Comes with Python, no install needed
- Verbose, requires manual setup of each argument
- Good for simple tools, tedious for complex ones
- Docs: https://docs.python.org/3/library/argparse.html

**Click:**
- Third-party library, uses decorators to define commands
- Mature, well-documented, widely used
- Docs: https://click.palletsprojects.com/

**Typer (our choice):**
- Built on top of Click, uses Python type hints instead of decorators
- Less boilerplate: function parameters become CLI arguments automatically
- Auto-generates `--help` text from docstrings and type annotations
- Works seamlessly with Rich for colored output
- Official docs: https://typer.tiangolo.com/
- Tutorial: https://typer.tiangolo.com/tutorial/
- Real Python tutorial: https://realpython.com/python-typer-cli/
- KDnuggets tutorial: https://www.kdnuggets.com/python-typer-tutorial-build-clis-python
- Complete 2026 guide (Click + Typer): https://devtoolbox.dedyn.io/blog/python-click-typer-cli-guide

**Example Typer CLI:**
```python
import typer
from rich.table import Table
from rich.console import Console

app = typer.Typer()
console = Console()

@app.command()
def analyze(dockerfile: str, pulls_per_month: int = 100000):
    """Analyze a Dockerfile for carbon-wasteful patterns."""
    # parse, check rules, estimate carbon, print table
    table = Table(title="Findings")
    table.add_column("Issue")
    table.add_column("Fix")
    table.add_column("CO2/month")
    console.print(table)

if __name__ == "__main__":
    app()
```

---

## 2. How Docker Images Work

### Basics

A Docker image is a read-only template used to create containers. It consists of stacked **layers**, where each layer represents a filesystem change.

### Layers

- Each `FROM`, `RUN`, `COPY`, and `ADD` instruction in a Dockerfile creates a new layer
- Layers are immutable and content-addressable (identified by SHA256 hash)
- Docker caches layers - if a layer hasn't changed, it's reused from cache
- A union filesystem stacks all layers to present a single filesystem view

### Why Layers Matter for Our Project

- More unnecessary layers = more storage and transfer overhead
- Uncombined `RUN` commands create separate layers where cleanup in a later layer doesn't actually reduce image size (the files still exist in the earlier layer)
- This is why `RUN apt-get install -y gcc && ... && apt-get purge -y gcc` must be in ONE layer

### Image Registries

Images are stored in registries (Docker Hub is the default). When you `docker pull python:3.12`, Docker downloads each layer from Docker Hub. The transfer size is the **compressed** size of all layers.

### Key Reading

- Docker docs - Understanding image layers: https://docs.docker.com/get-started/docker-concepts/building-images/understanding-image-layers/
- Spacelift - Docker Image Layers explained: https://spacelift.io/blog/docker-image-layers
- DZone - Docker Layers Explained: https://dzone.com/articles/docker-layers-explained
- KodeKloud - What Are Docker Image Layers: https://kodekloud.com/blog/docker-image-layers/

---

## 3. Dockerfile Syntax and Parsing

### Key Dockerfile Instructions

| Instruction | Purpose |
|-------------|---------|
| `FROM` | Sets the base image (starts a new build stage) |
| `RUN` | Executes a command and creates a new layer |
| `COPY` / `ADD` | Copies files from build context into the image |
| `WORKDIR` | Sets the working directory |
| `EXPOSE` | Documents which port the container listens on |
| `CMD` / `ENTRYPOINT` | Defines the default command to run |
| `ARG` | Defines a build-time variable |
| `ENV` | Sets an environment variable |

### dockerfile-parse Library

**Our tool for parsing Dockerfiles.** A Python library by Red Hat's Container Build System team.

- GitHub: https://github.com/containerbuildsystem/dockerfile-parse
- PyPI: https://pypi.org/project/dockerfile-parse/

**How it works:**
```python
from dockerfile_parse import DockerfileParser

dfp = DockerfileParser()
dfp.content = "FROM python:3.12\nRUN pip install flask\n"

# Get base image
print(dfp.baseimage)  # "python:3.12"

# Get structured instructions
for instruction in dfp.structure:
    print(instruction)
    # {'instruction': 'FROM', 'startline': 0, 'endline': 0, 'value': 'python:3.12', ...}
    # {'instruction': 'RUN', 'startline': 1, 'endline': 1, 'value': 'pip install flask', ...}
```

The `.structure` property returns a list of dicts, each with:
- `instruction`: the Dockerfile command (FROM, RUN, COPY, etc.)
- `value`: the argument string
- `startline` / `endline`: line positions in the file

**Alternative:** The `dockerfile` PyPI package (https://pypi.org/project/dockerfile/) wraps Go's moby/buildkit parser but requires CGo compilation - harder to install cross-platform.

---

## 4. Docker Hub API

Docker Hub provides a REST API to query image metadata including pull counts.

### Get Image Info (Pull Count)

**For official images (library namespace):**
```
GET https://hub.docker.com/v2/repositories/library/{image}/
```

**For user/org images:**
```
GET https://hub.docker.com/v2/repositories/{namespace}/{image}/
```

**Response includes:**
```json
{
  "name": "python",
  "namespace": "library",
  "pull_count": 1234567890,
  "star_count": 8765,
  "date_registered": "2014-05-08T...",
  "last_updated": "2024-03-15T..."
}
```

**Estimating monthly pulls:**
```python
monthly_pulls = pull_count / months_since_registration
```

### Get Image Tags (for size data)

```
GET https://hub.docker.com/v2/repositories/library/{image}/tags/?page_size=100
```

Returns tag names and compressed sizes, useful for building `image_sizes.json`.

### Rate Limits

Read-only API calls have generous limits (thousands per minute). No authentication needed for public repos. Does not count against Docker pull rate limits.

### References

- Docker Hub API docs: https://docs.docker.com/docker-hub/repos/manage/trusted-content/insights-analytics/
- Blog post on tracking Docker Hub metrics: https://brianchristner.io/how-to-track-docker-hub-metrics/
- DockerHub API to Get Statistics: https://bastide.org/2021/11/10/dockerhub-api-to-get-statistics/
- Analyzing DockerHub Pull Counts: https://altinity.com/blog/analyzing-dockerhub-pull-counts-with-clickhouse-and-altinity-cloud

---

## 5. Carbon Estimation Model

### The Core Paper: Aslan et al. (2018)

**"Electricity Intensity of Internet Data Transmission: Untangling the Estimates"**
- Journal of Industrial Ecology, Vol 22(4), pp. 785-798
- Paper: https://onlinelibrary.wiley.com/doi/abs/10.1111/jiec.12630
- ResearchGate: https://www.researchgate.net/publication/318845230
- Semantic Scholar: https://www.semanticscholar.org/paper/Electricity-Intensity-of-Internet-Data-Untangling-Aslan-Mayers/b9983f06a2cfce3898efe05f29d1dfb1ed64f158

**Key findings:**
- The electricity intensity of data transmission was ~0.06 kWh/GB in 2015
- This intensity has been **halving every ~2 years** since 2000 (for developed countries)
- This rate of improvement is comparable to computing efficiency (Moore's Law-adjacent)

**How we use it:**
```
kWh_per_GB(year) = 0.06 * (0.5 ^ ((year - 2015) / 2))

For 2026: 0.06 * (0.5 ^ (11/2)) = 0.06 * 0.022 = ~0.00132 kWh/GB
```

**Note:** Extrapolating the halving rate to 2026 gives very small values. The paper itself cautions about extrapolation. We should:
- Report estimates as ranges (pessimistic: no improvement since 2018, optimistic: continued halving)
- Document all parameters and let users override them

### Follow-up Paper: Guennebaud (2024)

"Energy consumption of data transfer: Intensity indicators versus absolute estimates"
- Journal of Industrial Ecology
- Paper: https://onlinelibrary.wiley.com/doi/10.1111/jiec.13513
- Discusses limitations of the intensity approach

### Grid Carbon Intensity (gCO2/kWh)

Grid carbon intensity tells you how much CO2 is emitted per kWh of electricity, depending on the region's energy mix (coal, gas, nuclear, renewables).

**Data sources:**
- IEA Emission Factors 2023: https://www.iea.org/data-and-statistics/data-product/emissions-factors-2023
- IEA Emission Factors 2025: https://www.iea.org/data-and-statistics/data-product/emissions-factors-2025
- Climatiq (uses IEA data): https://www.climatiq.io/data/source/iea
- IEA Methodology documentation: https://iea.blob.core.windows.net/assets/bf862218-7fd8-4637-aca6-5a347b6ca4f1/IEA_Methodology_Emission_Factors_2023.pdf
- CarbonFootprint.com international factors: https://www.carbonfootprint.com/international_electricity_factors.html

**Example values (gCO2/kWh):**
| Region | gCO2/kWh |
|--------|----------|
| World average | ~436 |
| France | ~56 (mostly nuclear) |
| Netherlands | ~328 |
| Germany | ~350 |
| USA average | ~390 |
| India | ~632 |
| China | ~555 |

### The Carbon Formula

```
CO2_per_month (grams) = size_saved_GB * pulls_per_month * kWh_per_GB * grid_gCO2_per_kWh

CO2_per_month (kg) = above / 1000
```

### CO2.js Library

The Green Web Foundation's open-source library for data-to-carbon conversion. Good reference for how others implement similar calculations.
- GitHub: https://github.com/thegreenwebfoundation/co2.js

### Other Key Papers

- Masanet et al. (2020). "Recalibrating global data center energy-use estimates." Science.
  - https://www.science.org/doi/abs/10.1126/science.aba3758
- Energy intensity blog post with detailed analysis: https://blog.mynl.com/posts/notes/2024-05-21-Energy-Intensity-of-Internet-Traffic/

---

## 6. Energy Measurement Tools

### CodeCarbon (Primary Choice)

Python library that tracks CPU/GPU/RAM electricity consumption and converts to CO2 emissions.

- GitHub: https://github.com/mlco2/codecarbon
- Website: https://codecarbon.io/
- PyPI: https://pypi.org/project/codecarbon/
- Tutorial: https://github.com/Kerl1310/codecarbon_tutorial
- Medium guide: https://medium.com/@elvenkim1/measure-carbon-emission-of-python-program-using-codecarbon-io-c41bd2225f8c
- Intro blog: https://www.comet.com/site/blog/introducing-codecarbon-an-open-source-tool-to-help-track-the-co2-emissions-of-your-research/

**How to use:**
```python
from codecarbon import EmissionsTracker

tracker = EmissionsTracker()
tracker.start()

# ... run docker build here ...

emissions = tracker.stop()
print(f"Energy consumed: {tracker._total_energy.kWh} kWh")
print(f"CO2 emissions: {emissions} kg")
```

**How it works internally:**
- Reads Intel RAPL (Running Average Power Limit) counters for CPU energy
- Uses nvidia-smi for GPU power
- Estimates RAM power from capacity
- Multiplies total power by execution time
- Applies regional grid carbon intensity

### EnergiBridge (Secondary / Academic)

Cross-platform energy measurement utility developed by TU Delft researchers. Relevant because the course instructor (Luis Cruz) created the Python wrapper.

- GitHub: https://github.com/tdurieux/EnergiBridge
- Python wrapper (pyEnergiBridge): https://github.com/luiscruz/pyEnergiBridge
- Paper: https://arxiv.org/abs/2312.13897

**How to use:**
```python
from pyenergibidge import EnergyMeasurement

with EnergyMeasurement() as em:
    # ... run docker build ...
    pass

print(f"Energy: {em.energy_joules} J")
```

Requires the EnergiBridge binary installed separately (available from GitHub releases).

### Other Energy Measurement Tools (mentioned in proposal)

- **Scaphandre** - energy consumption metrology agent with Docker/K8s support
  - GitHub: https://github.com/hubblo-org/scaphandre
- **PowerJoular** - monitors CPU/GPU power via Intel RAPL and ARM interfaces
  - GitHub: https://github.com/joular/powerjoular
- **Linux perf stat** - built-in profiler that reads RAPL energy counters
  - Usage: `sudo perf stat -e power/energy-pkg/ docker build .`

---

## 7. Python Packaging with pyproject.toml

`pyproject.toml` is the modern standard for configuring Python packages (replaces setup.py/setup.cfg).

### Key Concepts

- **`[project]`**: Package metadata (name, version, dependencies)
- **`[project.scripts]`**: Creates CLI commands. `dco = "dco.cli:app"` means: when user types `dco`, Python calls the `app` object in `dco/cli.py`
- **`[project.optional-dependencies]`**: Extra dependency groups installed with `pip install .[dev]`
- **`[build-system]`**: Which build backend to use (setuptools, hatchling, flit, etc.)

### References

- Official Python Packaging guide: https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
- pyproject.toml specification: https://packaging.python.org/en/latest/specifications/pyproject-toml/
- Real Python guide: https://realpython.com/python-pyproject-toml/
- PyOpenSci guide: https://www.pyopensci.org/python-package-guide/package-structure-code/pyproject-toml-python-package-metadata.html
- Simon Willison's minimal example: https://til.simonwillison.net/python/pyproject
- Entry points with Click/Typer: https://click.palletsprojects.com/en/stable/entry-points/
- Setuptools entry points: https://setuptools.pypa.io/en/latest/userguide/entry_point.html

---

## 8. Rich Library (Terminal Output)

Rich is a Python library for rich text and beautiful formatting in the terminal. We use it for the findings table output.

### Key Features We Use

- **Tables**: `rich.table.Table` for the findings output
- **Console**: `rich.console.Console` for styled printing
- **Progress bars**: For batch analysis of multiple Dockerfiles
- **Panels**: For summary statistics
- **Colors/Styles**: Severity-colored output (red for high, yellow for medium)

### References

- GitHub: https://github.com/Textualize/rich
- Docs - Tables: https://rich.readthedocs.io/en/stable/tables.html
- Docs - Introduction: https://rich.readthedocs.io/en/stable/introduction.html
- FreeCodeCamp tutorial: https://www.freecodecamp.org/news/use-the-rich-library-in-python/
- Open Source Automation tutorial: https://theautomatic.net/2021/01/05/pythons-rich-library-a-tutorial/

**Example table:**
```python
from rich.table import Table
from rich.console import Console

console = Console()
table = Table(title="DCO Findings")
table.add_column("Rule", style="cyan")
table.add_column("Issue", style="white")
table.add_column("Fix", style="green")
table.add_column("Size Saved", justify="right")
table.add_column("CO2/month", justify="right", style="red")

table.add_row("DCO001", "Oversized base image", "Use python:3.12-slim", "855 MB", "~2.2 kg")
console.print(table)
```

---

## 9. Testing with pytest

pytest is the standard Python testing framework. It discovers test files automatically and uses simple `assert` statements.

### Key Concepts

- **Test discovery**: Files named `test_*.py`, functions named `test_*`
- **Fixtures**: Reusable setup/teardown with `@pytest.fixture`
- **Parametrize**: Run the same test with different inputs using `@pytest.mark.parametrize`
- **Coverage**: `pytest-cov` plugin measures code coverage

### References

- Official docs: https://docs.pytest.org/en/stable/getting-started.html
- Real Python tutorial: https://realpython.com/pytest-python-testing/
- FreeCodeCamp guide: https://www.freecodecamp.org/news/how-to-use-pytest-a-guide-to-testing-in-python/
- Better Stack guide: https://betterstack.com/community/guides/testing/pytest-guide/
- GeeksforGeeks tutorial: https://www.geeksforgeeks.org/python/pytest-tutorial-testing-python-application-using-pytest/

### Testing HTTP calls

Use **respx** (for httpx) or **responses** (for requests) to mock HTTP calls to Docker Hub API in tests, so tests don't depend on network access.

---

## 10. Existing Dockerfile Linters

### Hadolint

The most popular Dockerfile linter. Parses Dockerfiles into an AST, applies rules, and uses ShellCheck to lint bash inside RUN instructions.

- GitHub: https://github.com/hadolint/hadolint
- Online: https://hadolint.github.io/hadolint/
- Docker Hub: https://hub.docker.com/r/hadolint/hadolint
- DevOpsCube guide: https://devopscube.com/lint-dockerfiles-using-hadolint/
- 2026 tutorial: https://oneuptime.com/blog/post/2026-02-08-how-to-lint-dockerfiles-with-hadolint/view

**What hadolint does:** Checks Dockerfile best practices (pin versions, use COPY not ADD, avoid sudo, combine RUN commands, etc.). Rules have DL prefixes (DL3006: tag your base image, DL3003: use WORKDIR instead of cd, etc.).

**What hadolint does NOT do (our gap):** It does not estimate the carbon cost, energy impact, or size savings of its suggestions. It says "pin your version" but not "this wastes 855 MB and ~2.2 kg CO2/month." That's what our tool adds.

### Dockle

Container image linter focused on security and CIS benchmarks.

- GitHub: https://github.com/goodwithtech/dockle

**What it does:** Checks built images (not Dockerfiles) for security issues - running as root, sensitive files, setuid binaries.

**What it doesn't do:** No carbon or energy analysis.

---

## 11. Ruff (Linting & Formatting)

Ruff is an extremely fast Python linter and formatter that replaces flake8, black, and isort.

- GitHub: https://github.com/astral-sh/ruff
- Docs: https://docs.astral.sh/ruff/

Used in CI to enforce code quality across the team.

---

## 12. Auto-Fix: Generating Optimized Dockerfiles (`dco fix`)

Beyond analysis, the tool can **generate optimized Dockerfiles** by automatically applying fixes for detected issues.

### How dockerfile-parse Supports Modification

The `dockerfile-parse` library supports **writing** modifications, not just reading:

```python
from dockerfile_parse import DockerfileParser

dfp = DockerfileParser(path="./Dockerfile")

# Modify base image directly (DCO001 fix)
dfp.baseimage = "python:3.12-slim"

# Read/write labels, envs, args
dfp.labels = {"maintainer": "team@example.com"}
dfp.envs = {"APP_ENV": "production"}
dfp.args = {"VERSION": "1.0.0"}

# Add new lines
dfp.add_lines("RUN apt-get clean", base_image=False)

# The full content is available as a string
print(dfp.content)  # modified Dockerfile text
```

**Key properties for modification:**
- `dfp.baseimage = "image:tag"` - replaces the FROM line
- `dfp.content` - read/write the full Dockerfile as a string
- `dfp.add_lines(line)` - append instructions
- `dfp.labels`, `dfp.envs`, `dfp.args` - dict-based read/write

**Limitation:** There is no structured API for modifying individual RUN instructions. For RUN modifications (combining layers, adding purge commands), you must manipulate `dfp.content` as a string or rebuild from the `.structure` data.

### Fix Strategy Per Rule

| Rule | Auto-fix approach | Complexity |
|------|-------------------|------------|
| DCO001 (base image) | `dfp.baseimage = "python:3.12-slim"` - direct property setter | Easy |
| DCO002 (RUN layers) | Parse consecutive RUN values, join with ` && \`, rebuild as single RUN | Medium |
| DCO003 (dev deps) | Append `&& apt-get purge -y gcc build-essential && apt-get autoremove -y` to the RUN line | Medium |
| DCO004 (dockerignore) | Generate a `.dockerignore` file from a template | Easy |
| DCO005 (multi-stage) | Restructure into two FROM stages - requires understanding build vs runtime | Hard (skip for MVP) |
| DCO006 (pinning) | Look up latest stable tag from Docker Hub, replace in FROM line | Easy |

### Combining RUN Instructions Programmatically

```python
# Given consecutive RUN instructions from parser:
runs = [
    "apt-get update",
    "apt-get install -y curl",
    "pip install flask gunicorn"
]

# Combine with && and backslash continuation for readability
combined = "RUN " + " && \\\n    ".join(runs)

# Result:
# RUN apt-get update && \
#     apt-get install -y curl && \
#     pip install flask gunicorn
```

For more complex multi-line RUNs, Docker also supports **heredoc syntax** (Docker BuildKit 1.4+):
```dockerfile
RUN <<EOF
apt-get update
apt-get install -y curl
pip install flask gunicorn
EOF
```

### Generating .dockerignore Files

Template-based approach for DCO004 auto-fix:

```python
DOCKERIGNORE_TEMPLATES = {
    "python": [".git", "__pycache__/", "*.py[cod]", ".venv/", "dist/", "build/",
               ".env", ".pytest_cache/", "*.egg-info/", ".coverage", "htmlcov/"],
    "node": [".git", "node_modules/", "npm-debug.log", ".env", "dist/", "coverage/"],
    "go": [".git", "vendor/", "*.test", "*.out", ".env"],
    "default": [".git", ".gitignore", ".env", ".env.local", "*.md", "LICENSE",
                ".vscode/", ".idea/", ".DS_Store", "Thumbs.db", ".github/"]
}
```

References for .dockerignore patterns:
- Docker docs on .dockerignore: https://docs.docker.com/build/building/best-practices/#use-a-dockerignore-file
- Template library: https://dockerignore.com/
- Auto-generate from .gitignore: https://pypi.org/project/generate-dockerignore-from-gitignore/

### Existing Auto-Fix / Optimization Tools (Landscape)

No existing tool does what `dco fix` does (rewrite Dockerfiles with carbon-aware fixes). The closest tools:

- **SlimToolkit (DockerSlim)** - optimizes built *images* at runtime by removing unused files, but does NOT modify Dockerfiles
  - GitHub: https://github.com/slimtoolkit/slim
- **Dive** - inspects built images to identify wasted space layer-by-layer, but is analysis-only
  - GitHub: https://github.com/wagoodman/dive
- **Hadolint** - suggests fixes in its output but does NOT auto-apply them
- **Jinja2 templates** (jocker) - can generate Dockerfiles from templates, but requires manual template creation
  - GitHub: https://github.com/nir0s/jocker

Our `dco fix` command is unique in that it **rewrites existing Dockerfiles** with carbon-optimized alternatives.

### Implementation Architecture for `dco fix`

Each rule's `Finding` object needs an additional field to support auto-fix:

```python
@dataclass
class Finding:
    rule_id: str
    severity: str
    line: int
    issue: str
    fix: str                  # Human-readable fix description
    size_saved_mb: float
    original_size_mb: float
    auto_fixable: bool        # NEW: can this be auto-fixed?
    fix_action: FixAction | None  # NEW: structured fix instruction

@dataclass
class FixAction:
    action_type: str          # "replace_from", "combine_runs", "append_to_run",
                              # "generate_dockerignore", "pin_tag"
    target_lines: tuple[int, int]  # start_line, end_line in original Dockerfile
    new_content: str          # replacement text
```

The fixer module (`src/dco/fixer.py`) reads all `Finding` objects, sorts them by line number (bottom to top to avoid offset issues), and applies each `FixAction` to the Dockerfile content.

---

## 13. Summary: How It All Fits Together

```
User runs: dco analyze Dockerfile
  1. cli.py (Typer) parses the command
  2. parser.py (dockerfile-parse) reads and parses the Dockerfile
  3. rules/*.py check for anti-patterns, return Finding objects
  4. carbon/model.py estimates CO2 for each Finding
  5. output.py (Rich) formats findings into a colorful table
  6. Table is printed to terminal

User runs: dco fix Dockerfile
  1-4. Same as analyze (parse, check rules, estimate carbon)
  5. fixer.py reads Finding objects with FixAction data
  6. Applies fixes bottom-to-top to avoid line offset issues
  7. Writes optimized Dockerfile to Dockerfile.optimized (or --in-place)
  8. If DCO004 triggered, also generates .dockerignore
  9. Prints before/after summary (original size vs optimized size)
```
