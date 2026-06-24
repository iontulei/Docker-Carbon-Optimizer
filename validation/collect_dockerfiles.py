#!/usr/bin/env python3
"""Clone GitHub repos listed in repos.json for validation testing.

Usage:
    python validation/collect_dockerfiles.py [--repos validation/repos.json]

Clones each repo (shallow, depth=1) into validation/repos/<name>/.
Skips repos that are already cloned. Reports which repos have a
valid Dockerfile.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Possible Dockerfile locations (checked in order).
_DOCKERFILE_CANDIDATES = [
    "Dockerfile",
    "dockerfile",
    "docker/Dockerfile",
    "docker/dockerfile",
    ".docker/Dockerfile",
]

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPOS_JSON = SCRIPT_DIR / "repos.json"
REPOS_DIR = SCRIPT_DIR / "repos"


def find_dockerfile(repo_dir: Path) -> Path | None:
    """Return the first Dockerfile found in *repo_dir*, or None."""
    for candidate in _DOCKERFILE_CANDIDATES:
        path = repo_dir / candidate
        if path.exists():
            return path
    # Also check for any file starting with "Dockerfile" (e.g. Dockerfile.dev).
    for path in repo_dir.iterdir():
        if path.is_file() and path.name.lower().startswith("dockerfile"):
            return path
    return None


def clone_repo(url: str, dest: Path) -> bool:
    """Shallow-clone *url* into *dest*. Returns True on success."""
    if dest.exists():
        print(f"  Already cloned: {dest}")
        return True
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(f"  Clone FAILED: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  Clone FAILED: timeout (120s)")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone repos for DCO validation.")
    parser.add_argument(
        "--repos",
        type=Path,
        default=DEFAULT_REPOS_JSON,
        help="Path to repos.json (default: validation/repos.json)",
    )
    args = parser.parse_args()

    repos = json.loads(args.repos.read_text(encoding="utf-8"))
    REPOS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"=== Collecting {len(repos)} repos ===\n")

    summary: list[dict] = []
    for repo in repos:
        name = repo["name"]
        url = repo["url"]
        print(f"[{name}] ({repo['lang']}) - {url}")

        dest = REPOS_DIR / name
        cloned = clone_repo(url, dest)
        if not cloned:
            summary.append({"name": name, "status": "clone_failed"})
            continue

        if repo.get("dockerfile"):
            dockerfile = dest / repo["dockerfile"]
            if not dockerfile.exists():
                dockerfile = None
        else:
            dockerfile = find_dockerfile(dest)

        if dockerfile is None:
            print(f"  No Dockerfile found in {dest}")
            summary.append({"name": name, "status": "no_dockerfile"})
        else:
            rel = dockerfile.relative_to(dest)
            print(f"  Dockerfile: {rel}")
            summary.append({"name": name, "status": "ok", "dockerfile": str(rel)})
        print()

    # Summary
    ok = sum(1 for s in summary if s["status"] == "ok")
    print(f"=== Done: {ok}/{len(repos)} repos have Dockerfiles ===")
    for s in summary:
        status = s["status"]
        marker = "OK" if status == "ok" else "SKIP"
        extra = f" ({s.get('dockerfile', status)})" if status == "ok" else f" ({status})"
        print(f"  [{marker}] {s['name']}{extra}")

    if ok == 0:
        print("\nNo repos with Dockerfiles found. Check repos.json.")
        sys.exit(1)


if __name__ == "__main__":
    main()
