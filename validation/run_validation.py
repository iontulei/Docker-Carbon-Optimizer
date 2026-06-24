#!/usr/bin/env python3
"""Run DCO validation: analyze, fix, build before/after, measure energy.

Usage:
    python validation/run_validation.py [--repos validation/repos.json]

Prerequisites:
    - Docker Desktop running
    - pip install -e ".[dev,energy]"
    - Run collect_dockerfiles.py first (or this script clones automatically)

Output:
    validation/results/results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPOS_JSON = SCRIPT_DIR / "repos.json"
REPOS_DIR = SCRIPT_DIR / "repos"
RESULTS_DIR = SCRIPT_DIR / "results"
DOCKERFILES_DIR = SCRIPT_DIR / "dockerfiles"

# Maximum time for a single docker build (seconds).
BUILD_TIMEOUT = 1200  # 20 minutes

# Possible Dockerfile locations (checked in order).
_DOCKERFILE_CANDIDATES = [
    "Dockerfile",
    "dockerfile",
    "docker/Dockerfile",
    "docker/dockerfile",
    ".docker/Dockerfile",
]


def find_dockerfile(repo_dir: Path) -> Path | None:
    """Return the first Dockerfile found in *repo_dir*, or None."""
    for candidate in _DOCKERFILE_CANDIDATES:
        path = repo_dir / candidate
        if path.exists():
            return path
    for path in repo_dir.iterdir():
        if path.is_file() and path.name.lower().startswith("dockerfile"):
            return path
    return None


def clone_if_needed(url: str, dest: Path) -> bool:
    """Shallow-clone *url* into *dest* if not already present."""
    if dest.exists():
        return True
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def get_image_size_mb(image_tag: str) -> float:
    """Query Docker for the image size in MB."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image_tag,
             "--format", "{{.Size}}"],
            capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
        size_bytes = int(result.stdout.strip())
        return size_bytes / (1024 * 1024)
    except (subprocess.CalledProcessError, ValueError):
        return 0.0


def docker_build(
    tag: str,
    context_dir: Path,
    dockerfile: Path | None = None,
    no_cache: bool = False,
) -> tuple[bool, float]:
    """Run docker build and return (success, duration_seconds)."""
    cmd = ["docker", "build", "--pull", "-t", tag]
    if no_cache:
        cmd.append("--no-cache")
    if dockerfile is not None:
        cmd.extend(["-f", str(dockerfile)])
    cmd.append(".")

    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, cwd=context_dir,
            capture_output=True, text=True,
            timeout=BUILD_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
        duration = time.perf_counter() - t0
        return result.returncode == 0, duration
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - t0
        return False, duration


def measure_build(
    tag: str,
    context_dir: Path,
    dockerfile: Path | None = None,
    no_cache: bool = False,
) -> dict:
    """Build an image and measure energy with CodeCarbon if available.

    Returns a dict with keys: success, duration_s, energy_kwh, co2_g, size_mb.
    """
    energy_kwh = 0.0
    co2_g = 0.0

    try:
        from dco.carbon.build import BuildEnergyTracker

        tracker = BuildEnergyTracker(project_name=tag, log_level="error")
        if tracker.is_available():
            cmd = ["docker", "build", "--pull", "-t", tag]
            if no_cache:
                cmd.append("--no-cache")
            if dockerfile is not None:
                cmd.extend(["-f", str(dockerfile)])
            cmd.append(".")

            measurement = tracker.measure_command(
                cmd, cwd=context_dir, check=True,
            )
            size_mb = get_image_size_mb(tag)
            return {
                "success": True,
                "duration_s": measurement.duration_seconds,
                "energy_kwh": measurement.energy_kwh,
                "co2_g": measurement.co2_kg * 1000,
                "size_mb": size_mb,
            }
    except Exception as exc:
        print(f"\n  [CodeCarbon failed: {exc}] Falling back to plain build.")

    # Fallback: build without energy measurement.
    success, duration = docker_build(tag, context_dir, dockerfile, no_cache)
    size_mb = get_image_size_mb(tag) if success else 0.0
    return {
        "success": success,
        "duration_s": duration,
        "energy_kwh": energy_kwh,
        "co2_g": co2_g,
        "size_mb": size_mb,
    }


def run_dco_analyze(dockerfile: Path) -> dict | None:
    """Run dco analyze --format json and return parsed output."""
    try:
        result = subprocess.run(
            ["dco", "analyze", str(dockerfile), "--no-dockerhub", "--format", "json"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return None


def run_dco_fix(dockerfile: Path, force: bool = True) -> bool:
    """Run dco fix --in-place. Uses --force unless *force* is False."""
    cmd = ["dco", "fix", str(dockerfile), "--in-place"]
    if force:
        cmd.insert(3, "--force")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30,
            input="y\n",  # Confirm in-place overwrite.
            encoding="utf-8", errors="replace",
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def cleanup_images(*tags: str) -> None:
    """Remove Docker images to free disk space."""
    for tag in tags:
        subprocess.run(
            ["docker", "rmi", "-f", tag],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DCO validation pipeline.")
    parser.add_argument(
        "--repos", type=Path, default=DEFAULT_REPOS_JSON,
        help="Path to repos.json",
    )
    args = parser.parse_args()

    repos = json.loads(args.repos.read_text(encoding="utf-8"))
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Check Docker is running.
    docker_check = subprocess.run(
        ["docker", "info"], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if docker_check.returncode != 0:
        print("ERROR: Docker is not running. Start Docker Desktop and retry.")
        sys.exit(1)

    print(f"=== DCO Validation: {len(repos)} repos ===\n")

    results: list[dict] = []

    for i, repo in enumerate(repos, 1):
        name = repo["name"]
        url = repo["url"]
        lang = repo["lang"]
        before_tag = f"dco-before-{name}"
        after_tag = f"dco-after-{name}"

        print(f"[{i}/{len(repos)}] {name} ({lang})")
        print(f"  URL: {url}")

        row = {
            "repo": name,
            "lang": lang,
            "findings": 0,
            "rules_triggered": "",
            "size_before_mb": 0.0,
            "size_after_mb": 0.0,
            "size_delta_mb": 0.0,
            "time_before_s": 0.0,
            "time_after_s": 0.0,
            "energy_before_kwh": 0.0,
            "energy_after_kwh": 0.0,
            "co2_before_g": 0.0,
            "co2_after_g": 0.0,
            "build_before": "skip",
            "build_after": "skip",
        }

        # 1. Clone
        repo_dir = REPOS_DIR / name
        if not clone_if_needed(url, repo_dir):
            print("  SKIP: clone failed")
            row["build_before"] = "clone_failed"
            results.append(row)
            print()
            continue

        # 2. Find Dockerfile (use repos.json hint or auto-detect)
        if repo.get("dockerfile"):
            dockerfile = repo_dir / repo["dockerfile"]
            if not dockerfile.exists():
                dockerfile = None
        else:
            dockerfile = find_dockerfile(repo_dir)

        # Build context directory (some repos have Dockerfile in a subdirectory)
        context_dir = repo_dir / repo.get("context", ".") if repo.get("context") else repo_dir

        if dockerfile is None:
            print("  SKIP: no Dockerfile found")
            row["build_before"] = "no_dockerfile"
            results.append(row)
            print()
            continue

        print(f"  Dockerfile: {dockerfile.relative_to(repo_dir)}")

        # 2b. Copy un-optimized Dockerfile from dockerfiles/<name>/ if present
        custom_df = DOCKERFILES_DIR / name / "Dockerfile"
        if custom_df.exists():
            shutil.copy2(custom_df, dockerfile)
            print("  Replaced with un-optimized Dockerfile")

        # 2c. Delete .dockerignore if flagged (to trigger DCO004)
        dockerignore_backup = None
        if repo.get("delete_dockerignore"):
            di_path = context_dir / ".dockerignore"
            if di_path.exists():
                dockerignore_backup = di_path.with_suffix(".bak")
                shutil.move(str(di_path), str(dockerignore_backup))
                print("  Renamed .dockerignore (DCO004)")

        # 3. Analyze
        analysis = run_dco_analyze(dockerfile)
        if analysis:
            row["findings"] = analysis["summary"]["total_findings"]
            rules = set(f["rule_id"] for f in analysis.get("findings", []))
            row["rules_triggered"] = ",".join(sorted(rules))
            print(f"  Findings: {row['findings']} ({row['rules_triggered']})")
        else:
            print("  Findings: analysis failed")

        # 4. Backup original Dockerfile
        backup = dockerfile.with_suffix(dockerfile.suffix + ".bak")
        shutil.copy2(dockerfile, backup)

        # 5. Prune Docker to ensure no cached images/layers
        print("  Pruning Docker cache...", end=" ", flush=True)
        subprocess.run(
            ["docker", "system", "prune", "-a", "-f"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        print("done")

        # 6. Build BEFORE
        print("  Building BEFORE...", end=" ", flush=True)
        before = measure_build(before_tag, context_dir, dockerfile, no_cache=True)
        row["build_before"] = "ok" if before["success"] else "failed"
        row["size_before_mb"] = round(before["size_mb"], 1)
        row["time_before_s"] = round(before["duration_s"], 1)
        row["energy_before_kwh"] = before["energy_kwh"]
        row["co2_before_g"] = round(before["co2_g"], 2)
        print(f"{'OK' if before['success'] else 'FAILED'} "
              f"({before['duration_s']:.1f}s, {before['size_mb']:.1f} MB)")

        if not before["success"]:
            # Restore and skip.
            shutil.move(str(backup), str(dockerfile))
            if dockerignore_backup and dockerignore_backup.exists():
                shutil.move(str(dockerignore_backup), str(context_dir / ".dockerignore"))
            cleanup_images(before_tag)
            results.append(row)
            print()
            continue

        # 6. Fix
        use_force = not repo.get("no_force", False)
        force_label = " --force" if use_force else ""
        print(f"  Applying dco fix{force_label}...", end=" ", flush=True)
        fixed = run_dco_fix(dockerfile, force=use_force)
        print("OK" if fixed else "FAILED")

        if not fixed:
            shutil.move(str(backup), str(dockerfile))
            if dockerignore_backup and dockerignore_backup.exists():
                shutil.move(str(dockerignore_backup), str(context_dir / ".dockerignore"))
            cleanup_images(before_tag)
            results.append(row)
            print()
            continue

        # 7. Prune again so AFTER doesn't reuse BEFORE's base image
        print("  Pruning Docker cache...", end=" ", flush=True)
        cleanup_images(before_tag)
        subprocess.run(
            ["docker", "system", "prune", "-a", "-f"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        print("done")

        # 8. Build AFTER (fully fresh)
        print("  Building AFTER...", end=" ", flush=True)
        after = measure_build(after_tag, context_dir, dockerfile, no_cache=True)
        row["build_after"] = "ok" if after["success"] else "failed"
        row["size_after_mb"] = round(after["size_mb"], 1)
        row["time_after_s"] = round(after["duration_s"], 1)
        row["energy_after_kwh"] = after["energy_kwh"]
        row["co2_after_g"] = round(after["co2_g"], 2)
        print(f"{'OK' if after['success'] else 'FAILED'} "
              f"({after['duration_s']:.1f}s, {after['size_mb']:.1f} MB)")

        # 8. Compute deltas
        if before["success"] and after["success"]:
            row["size_delta_mb"] = round(
                before["size_mb"] - after["size_mb"], 1
            )

        # 9. Restore original Dockerfile and .dockerignore
        shutil.move(str(backup), str(dockerfile))
        if dockerignore_backup and dockerignore_backup.exists():
            shutil.move(str(dockerignore_backup), str(context_dir / ".dockerignore"))

        # 10. Cleanup images
        cleanup_images(before_tag, after_tag)

        results.append(row)
        print()

    # Write CSV
    csv_path = RESULTS_DIR / "results.csv"
    fieldnames = [
        "repo", "lang", "findings", "rules_triggered",
        "size_before_mb", "size_after_mb", "size_delta_mb",
        "time_before_s", "time_after_s",
        "energy_before_kwh", "energy_after_kwh",
        "co2_before_g", "co2_after_g",
        "build_before", "build_after",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"=== Results written to {csv_path} ===\n")

    # Print summary
    built_before = sum(1 for r in results if r["build_before"] == "ok")
    built_both = sum(
        1 for r in results
        if r["build_before"] == "ok" and r["build_after"] == "ok"
    )
    total_size_saved = sum(r["size_delta_mb"] for r in results)
    print(f"Repos tested:         {len(results)}")
    print(f"Built (before):       {built_before}/{len(results)}")
    print(f"Built (before+after): {built_both}/{len(results)}")
    print(f"Total size saved:     {total_size_saved:.1f} MB")


if __name__ == "__main__":
    main()
