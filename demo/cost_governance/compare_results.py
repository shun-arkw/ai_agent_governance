"""Render a compact Markdown comparison from cost experiment JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def summarize(document: dict[str, Any], source: Path) -> dict[str, Any]:
    results = document.get("results", [])
    called = [row for row in results if row.get("metadata", {}).get("api_called", True)]
    stopped = [row for row in results if row.get("stopped")]
    tokens = sum(int(row.get("usage", {}).get("total_tokens", 0)) for row in results)
    return {
        "source": source.name,
        "experiment": document.get("experiment", "unknown"),
        "tasks": len(results),
        "api_calls": len(called),
        "stopped": len(stopped),
        "tokens": tokens,
        "cost": float(document.get("total_effective_cost_usd", 0.0)),
    }


def markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Result | Experiment | Tasks | API calls | Stopped | Tokens | Effective Cost (USD) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['source']} | {row['experiment']} | {row['tasks']} | {row['api_calls']} | "
            f"{row['stopped']} | {row['tokens']} | {row['cost']:.8f} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    args = parser.parse_args()
    rows = [summarize(json.loads(path.read_text(encoding="utf-8")), path) for path in args.results]
    print(markdown(rows))


if __name__ == "__main__":
    main()
