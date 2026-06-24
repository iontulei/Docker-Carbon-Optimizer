"""CLI entry point for the Dockerfile Carbon Optimizer."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from dco import __version__
from dco.config import DEFAULT_OUTPUT_FORMAT, DEFAULT_PULLS_PER_MONTH, DEFAULT_REGION
from dco.fixer import apply_external_fixes, apply_fixes, validate_fix, write_fix
from dco.output import (
    format_findings_csv,
    format_findings_json,
    print_findings_table,
    print_fix_diff,
    print_fix_summary,
)
from dco.carbon.pull_frequency import get_pulls_per_month
from dco.parser import parse_file
from dco.rules import Finding, discover_rules, get_all_rules

app = typer.Typer(
    name="dco",
    help="Dockerfile Carbon Optimizer - Analyze and fix Dockerfiles for sustainability.",
    add_completion=False,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dco {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=version_callback, is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Dockerfile Carbon Optimizer - Analyze and fix Dockerfiles for sustainability."""


def _run_analysis(
    dockerfile: Path,
    pulls_per_month: int | None,
    region: str,
    no_dockerhub: bool,
) -> tuple[list[Finding], float]:
    """Parse a Dockerfile and run all registered rules against it.

    Returns (findings, actual_pulls_per_month).

    Pull count priority:
    1. Explicit ``--pulls-per-month`` (when provided) always wins.
    2. Otherwise, fetch real rate from Docker Hub (unless ``--no-dockerhub``).
    3. Fall back to DEFAULT_PULLS_PER_MONTH.
    """
    discover_rules()
    parsed = parse_file(dockerfile)

    if pulls_per_month is not None:
        # User explicitly set --pulls-per-month - honour it.
        actual_pulls: float = pulls_per_month
    elif not no_dockerhub and parsed.baseimage:
        # Fetch real pull rate from Docker Hub.
        actual_pulls = get_pulls_per_month(
            parsed.baseimage, fallback=DEFAULT_PULLS_PER_MONTH
        )
    else:
        actual_pulls = DEFAULT_PULLS_PER_MONTH

    context = {
        "dockerfile_dir": dockerfile.parent,
    }

    findings: list[Finding] = []
    for rule in get_all_rules():
        findings.extend(rule.check(parsed, context))

    # Sort by severity, then line number
    findings.sort(
        key=lambda f: (
            {"high": 0, "medium": 1, "low": 2}.get(f.severity, 3),
            f.line,
        )
    )
    return findings, actual_pulls


@app.command()
def analyze(
    dockerfile: Path = typer.Argument(..., help="Path to Dockerfile to analyze."),
    pulls_per_month: Optional[int] = typer.Option(
        None, help="Override monthly pull count for CO2 estimation (default: fetch from Docker Hub)."
    ),
    region: str = typer.Option(DEFAULT_REGION, help="Grid region for carbon intensity."),
    format: str = typer.Option(DEFAULT_OUTPUT_FORMAT, help="Output format: table, json, csv."),
    no_dockerhub: bool = typer.Option(False, help="Skip Docker Hub API calls."),
    output: Optional[Path] = typer.Option(None, help="Write results to file."),
) -> None:
    """Analyze a Dockerfile for energy-wasteful patterns."""
    if not dockerfile.exists():
        console.print(f"[red]Error: File not found: {dockerfile}[/red]")
        raise typer.Exit(code=1)

    findings, actual_pulls = _run_analysis(
        dockerfile, pulls_per_month, region, no_dockerhub
    )

    if format == "json":
        text = format_findings_json(findings, actual_pulls, region)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text)
    elif format == "csv":
        text = format_findings_csv(findings, actual_pulls, region)
        if output:
            output.write_text(text, encoding="utf-8")
        else:
            typer.echo(text)
    else:
        print_findings_table(findings, console, actual_pulls, region)


@app.command()
def fix(
    dockerfile: Path = typer.Argument(..., help="Path to Dockerfile to fix."),
    in_place: bool = typer.Option(False, help="Overwrite original file (asks confirmation)."),
    output_path: Optional[Path] = typer.Option(None, "--output", help="Output path for fixed Dockerfile."),
    rules: Optional[str] = typer.Option(None, help="Comma-separated rule IDs to fix (e.g. DCO001,DCO002)."),
    dry_run: bool = typer.Option(False, help="Show diff without writing changes."),
    force: bool = typer.Option(
        False, help="Also apply fixes marked as unsafe (e.g. base image swap)."
    ),
) -> None:
    """Generate an optimized version of a Dockerfile."""
    if not dockerfile.exists():
        console.print(f"[red]Error: File not found: {dockerfile}[/red]")
        raise typer.Exit(code=1)

    # Run analysis to detect issues (no Docker Hub call needed - fix doesn't show CO2).
    findings, _ = _run_analysis(
        dockerfile, pulls_per_month=None, region=DEFAULT_REGION, no_dockerhub=True
    )

    if not findings:
        console.print("[green]No issues found. Dockerfile looks good![/green]")
        raise typer.Exit()

    rules_filter = set(rules.split(",")) if rules else None
    content = dockerfile.read_text(encoding="utf-8")
    fix_result = apply_fixes(content, findings, rules_filter, force=force)

    if not fix_result.has_changes:
        console.print("[green]No auto-fixable issues found.[/green]")
        raise typer.Exit()

    # Validate the fix produces valid Dockerfile
    if not validate_fix(fix_result.fixed_content):
        console.print("[red]Error: Generated fix produces invalid Dockerfile. Aborting.[/red]")
        raise typer.Exit(code=1)

    if dry_run:
        print_fix_diff(fix_result, console)
        print_fix_summary(fix_result, console)
        raise typer.Exit()

    # Determine output path
    if in_place:
        confirm = typer.confirm(f"Overwrite {dockerfile}?")
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit()
        dest = dockerfile
    elif output_path:
        dest = output_path
    else:
        dest = dockerfile.with_suffix(dockerfile.suffix + ".optimized")

    write_fix(fix_result, dest)
    console.print(f"[green]Optimized Dockerfile written to: {dest}[/green]")

    # Handle external-file fixes (e.g. .dockerignore generation).
    ext_files = apply_external_fixes(findings, dockerfile.parent)
    for ef in ext_files:
        console.print(f"[green]Generated: {ef}[/green]")

    print_fix_diff(fix_result, console)
    print_fix_summary(fix_result, console)


@app.command()
def batch(
    directory: Path = typer.Argument(..., help="Directory to scan for Dockerfiles."),
    pulls_per_month: Optional[int] = typer.Option(
        None, help="Override monthly pull count for CO2 estimation."
    ),
    region: str = typer.Option(DEFAULT_REGION, help="Grid region for carbon intensity."),
    format: str = typer.Option(DEFAULT_OUTPUT_FORMAT, help="Output format: table, json, csv."),
    no_dockerhub: bool = typer.Option(False, help="Skip Docker Hub API calls."),
) -> None:
    """Analyze all Dockerfiles in a directory."""
    if not directory.is_dir():
        console.print(f"[red]Error: Not a directory: {directory}[/red]")
        raise typer.Exit(code=1)

    # Find Dockerfiles
    dockerfiles = sorted(
        set(
            list(directory.glob("*Dockerfile*"))
            + list(directory.glob("*.dockerfile"))
        )
    )

    if not dockerfiles:
        console.print(f"[yellow]No Dockerfiles found in {directory}[/yellow]")
        raise typer.Exit()

    console.print(f"Found {len(dockerfiles)} Dockerfile(s) in {directory}\n")

    all_results: dict[str, tuple[list[Finding], float]] = {}
    for df in dockerfiles:
        findings, actual_pulls = _run_analysis(
            df, pulls_per_month, region, no_dockerhub
        )
        all_results[str(df)] = (findings, actual_pulls)

    # Print results for each file
    for path, (findings, actual_pulls) in all_results.items():
        console.print(f"\n[bold]--- {path} ---[/bold]")
        if format == "json":
            typer.echo(format_findings_json(findings, actual_pulls, region))
        elif format == "csv":
            typer.echo(format_findings_csv(findings, actual_pulls, region))
        else:
            print_findings_table(findings, console, actual_pulls, region)

    # Batch summary
    total = sum(len(f) for f, _ in all_results.values())
    files_with_issues = sum(1 for f, _ in all_results.values() if f)
    console.print(f"\n[bold]Batch summary:[/bold] {total} finding(s) across {files_with_issues}/{len(dockerfiles)} file(s)")


@app.command()
def info(
    image: str = typer.Argument(..., help="Docker image name (e.g. python:3.12)."),
) -> None:
    """Show Docker Hub information for an image."""
    import httpx

    # Parse image name
    parts = image.split(":")
    name = parts[0]
    tag = parts[1] if len(parts) > 1 else "latest"

    # Normalize library images
    if "/" not in name:
        name = f"library/{name}"

    console.print(f"Fetching info for [bold]{image}[/bold]...")

    try:
        with httpx.Client() as client:
            # Get repository info
            resp = client.get(
                f"https://hub.docker.com/v2/repositories/{name}/",
                timeout=10.0,
            )
            if resp.status_code != 200:
                console.print(f"[red]Image not found on Docker Hub: {image}[/red]")
                raise typer.Exit(code=1)

            data = resp.json()
            pull_count = data.get("pull_count", "N/A")
            star_count = data.get("star_count", "N/A")
            description = data.get("description", "N/A")

            console.print(f"  Name:        {data.get('name', image)}")
            console.print(f"  Pulls:       {pull_count:,}" if isinstance(pull_count, int) else f"  Pulls:       {pull_count}")
            console.print(f"  Stars:       {star_count}")
            console.print(f"  Description: {description[:80]}")
            console.print(f"  Tag:         {tag}")

    except httpx.RequestError as e:
        console.print(f"[red]Error connecting to Docker Hub: {e}[/red]")
        raise typer.Exit(code=1)
