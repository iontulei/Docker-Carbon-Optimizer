"""Language-specific .dockerignore templates for DCO004 auto-fix."""

from __future__ import annotations

from pathlib import Path

_COMMON = """\
.git
.gitignore
.github
.env
.env.*
.venv
__pycache__
node_modules
.idea
.vscode
*.swp
*.swo
.DS_Store
Thumbs.db
"""

_PYTHON = """\
.git
.gitignore
.github
.env
.env.*
.venv
venv
env
__pycache__
*.pyc
*.pyo
*.pyd
*.egg-info
dist
build
.pytest_cache
.coverage
.mypy_cache
.ruff_cache
htmlcov
.tox
"""

_NODE = """\
.git
.gitignore
.github
.env
.env.*
node_modules
npm-debug.log*
yarn-error.log*
.npm
.eslintcache
dist
build
coverage
.next
"""

_GO = """\
.git
.gitignore
.github
.env
.env.*
vendor
*.test
*.out
bin
debug
"""

_JAVA = """\
.git
.gitignore
.github
.env
.env.*
target
*.class
.gradle
build
.classpath
.project
.settings
bin
"""

_TEMPLATES: dict[str, str] = {
    "python": _PYTHON,
    "node": _NODE,
    "go": _GO,
    "java": _JAVA,
}

_LANGUAGE_MARKERS: list[tuple[str, str]] = [
    ("go.mod", "go"),
    ("requirements.txt", "python"),
    ("pyproject.toml", "python"),
    ("setup.py", "python"),
    ("pom.xml", "java"),
    ("build.gradle", "java"),
    ("build.gradle.kts", "java"),
    ("package.json", "node"),
]


def detect_language(directory: Path) -> str | None:
    """Detect project language by looking for marker files in *directory*."""
    for filename, language in _LANGUAGE_MARKERS:
        if (directory / filename).exists():
            return language
    return None


def get_dockerignore_template(language: str | None = None) -> str:
    """Return a .dockerignore template for *language* (or a sensible default)."""
    return _TEMPLATES.get(language or "", _COMMON)
