"""Output formatting for DCO findings and fix results."""

from __future__ import annotations

import csv
import difflib
import io
import json
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from dco.carbon.estimator import estimate_co2_grams
from dco.config import DEFAULT_PULLS_PER_MONTH, DEFAULT_REGION, SEVERITY_COLORS

if TYPE_CHECKING:
    from dco.fixer import FixResult
    from dco.rules import Finding


def print_findings_table(
    findings: list[Finding],
    console: Console,
    pulls_per_month: int = DEFAULT_PULLS_PER_MONTH,
    region: str = DEFAULT_REGION,
) -> None:
    """Print findings as a Rich table."""
    if not findings:
        console.print("[green]No issues found.[/green]")
        return

    table = Table(title="DCO Analysis Results", show_lines=True)
    table.add_column("Rule", style="bold", width=8)
    table.add_column("Severity", width=8)
    table.add_column("Line", justify="right", width=5)
    table.add_column("Issue", width=40)
    table.add_column("Fix", width=35)
    table.add_column("Size Saved", justify="right", width=10)
    table.add_column("CO2/month", justify="right", width=12)

    for f in findings:
        severity_color = SEVERITY_COLORS.get(f.severity, "white")
        co2 = estimate_co2_grams(f.size_saved_mb, pulls_per_month, region)
        table.add_row(
            f.rule_id,
            f"[{severity_color}]{f.severity}[/{severity_color}]",
            str(f.line + 1),  # Convert 0-indexed to 1-indexed for display
            f.issue,
            f.fix,
            f"{f.size_saved_mb:.1f} MB",
            f"{co2:.1f} g",
        )

    console.print(table)
    _print_summary(findings, console, pulls_per_month, region)


def _print_summary(
    findings: list[Finding],
    console: Console,
    pulls_per_month: int,
    region: str = DEFAULT_REGION,
) -> None:
    """Print a summary panel below the findings table."""
    total_size = sum(f.size_saved_mb for f in findings)
    total_co2 = sum(
        estimate_co2_grams(f.size_saved_mb, pulls_per_month, region)
        for f in findings
    )
    fixable = sum(1 for f in findings if f.auto_fixable)

    summary = (
        f"Total findings: {len(findings)}\n"
        f"Auto-fixable: {fixable}\n"
        f"Potential size savings: {total_size:.1f} MB\n"
        f"Estimated CO2 savings: {total_co2:.1f} g/month "
        f"(at {pulls_per_month:,} pulls/month, region: {region})"
    )
    console.print(Panel(summary, title="Summary", border_style="blue"))


def format_findings_json(
    findings: list[Finding],
    pulls_per_month: int = DEFAULT_PULLS_PER_MONTH,
    region: str = DEFAULT_REGION,
) -> str:
    """Format findings as JSON string."""
    data = {
        "findings": [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "line": f.line + 1,
                "issue": f.issue,
                "fix": f.fix,
                "size_saved_mb": f.size_saved_mb,
                "co2_grams_per_month": round(
                    estimate_co2_grams(f.size_saved_mb, pulls_per_month, region), 2
                ),
                "auto_fixable": f.auto_fixable,
            }
            for f in findings
        ],
        "summary": {
            "total_findings": len(findings),
            "total_size_saved_mb": round(
                sum(f.size_saved_mb for f in findings), 2
            ),
            "total_co2_grams_per_month": round(
                sum(
                    estimate_co2_grams(f.size_saved_mb, pulls_per_month, region)
                    for f in findings
                ),
                2,
            ),
        },
    }
    return json.dumps(data, indent=2)


def format_findings_csv(
    findings: list[Finding],
    pulls_per_month: int = DEFAULT_PULLS_PER_MONTH,
    region: str = DEFAULT_REGION,
) -> str:
    """Format findings as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["rule_id", "severity", "line", "issue", "fix",
         "size_saved_mb", "co2_grams_per_month"]
    )
    for f in findings:
        co2 = estimate_co2_grams(f.size_saved_mb, pulls_per_month, region)
        writer.writerow(
            [f.rule_id, f.severity, f.line + 1, f.issue, f.fix,
             f.size_saved_mb, round(co2, 2)]
        )
    return output.getvalue()


def print_fix_diff(fix_result: FixResult, console: Console) -> None:
    """Print a unified diff of original vs fixed content."""
    diff = difflib.unified_diff(
        fix_result.original_content.splitlines(keepends=True),
        fix_result.fixed_content.splitlines(keepends=True),
        fromfile="original",
        tofile="optimized",
    )
    diff_text = "".join(diff)
    if diff_text:
        console.print(Panel(diff_text, title="Changes", border_style="yellow"))
    else:
        console.print("[green]No changes needed.[/green]")


def print_fix_summary(fix_result: FixResult, console: Console) -> None:
    """Print a summary of applied and skipped fixes."""
    applied = len(fix_result.applied_fixes)
    skipped = len(fix_result.skipped_fixes)
    console.print(f"[green]Applied {applied} fix(es)[/green]")
    if skipped:
        console.print(
            f"[yellow]Skipped {skipped} finding(s) (not auto-fixable)[/yellow]"
        )
