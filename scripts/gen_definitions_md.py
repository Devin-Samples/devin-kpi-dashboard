"""Render the KPI definitions registry to Markdown (for README/definitions page).

Usage: python scripts/gen_definitions_md.py > KPI_DEFINITIONS.md
"""

from __future__ import annotations

from devin_kpi.kpis.definitions import DEFINITIONS


def render() -> str:
    lines = ["# KPI definitions", ""]
    groups: dict[str, list[tuple[str, dict]]] = {}
    for key, d in DEFINITIONS.items():
        groups.setdefault(d["group"], []).append((key, d))
    for group, items in groups.items():
        lines += [
            f"## {group}",
            "",
            "| KPI | Formula | Source | Depends on |",
            "| --- | --- | --- | --- |",
        ]
        for key, d in items:
            dep = ", ".join(d["depends_on"]) or "—"
            lines.append(f"| {d['label']} (`{key}`) | {d['formula']} | {d['source']} | {dep} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(render())
