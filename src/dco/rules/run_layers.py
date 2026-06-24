"""DCO002: Detect uncombined consecutive RUN instructions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dco.rules import Finding, FixAction, register

if TYPE_CHECKING:
    from dco.parser import ParsedDockerfile

@register
class RunLayersRule:
    rule_id = "DCO002"
    name = "Uncombined RUN Layers"
    description = "Detects consecutive RUN instructions that could be combined with &&."

    def check(self, parsed_dockerfile: ParsedDockerfile, context: dict) -> list[Finding]:
        findings: list[Finding] = []
        instructions = parsed_dockerfile.instructions
        i = 0

        while i < len(instructions):
            if instructions[i]["instruction"] != "RUN":
                i += 1
                continue

            # Collect a group of consecutive RUN instructions.
            group = [instructions[i]]
            j = i + 1
            while j < len(instructions) and instructions[j]["instruction"] == "RUN":
                group.append(instructions[j])
                j += 1

            if len(group) >= 2:
                findings.append(self._make_finding(group))

            i = j  # skip past the group

        return findings

    # ------------------------------------------------------------------

    @staticmethod
    def _make_finding(group: list[dict]) -> Finding:
        extra_layers = len(group) - 1

        combined = " && \\\n    ".join(instr["value"] for instr in group)
        new_content = f"RUN {combined}\n"

        start_line = group[0]["startline"]
        end_line = group[-1]["endline"]

        return Finding(
            rule_id="DCO002",
            severity="medium",
            line=start_line,
            issue=(
                f"{len(group)} consecutive RUN instructions create {extra_layers} "
                f"unnecessary layer(s). Combine them with &&."
            ),
            fix="Merge consecutive RUN commands into a single RUN with && operators.",
            size_saved_mb=0.0,
            original_size_mb=0.0,
            auto_fixable=True,
            fix_action=FixAction(
                action_type="combine_runs",
                target_lines=(start_line, end_line),
                new_content=new_content,
            ),
        )
