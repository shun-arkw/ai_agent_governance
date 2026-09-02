"""Validate that every planned live experiment produced the expected control flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED = {
    "openai-sdk-baseline.json": (1, 0),
    "openai-sdk-max-turns-stop.json": (1, 1),
    "claude-sdk-baseline.json": (1, 0),
    "claude-sdk-budget-stop.json": (1, 1),
    "agt-openai-normal.json": (4, 0),
    "agt-openai-task-deny.json": (0, 4),
    "agt-openai-agent-deny.json": (2, 2),
    "agt-openai-org-deny.json": (1, 3),
    "agt-claude-normal.json": (4, 0),
    "agt-claude-task-deny.json": (0, 4),
    "agt-claude-agent-deny.json": (2, 2),
    "agt-claude-org-deny.json": (1, 3),
}


def validate(results_directory: Path) -> list[str]:
    lines: list[str] = []
    for filename, (expected_calls, expected_stopped) in EXPECTED.items():
        path = results_directory / filename
        if not path.exists():
            raise AssertionError(f"Missing result: {path}")
        document = json.loads(path.read_text(encoding="utf-8"))
        results = document["results"]
        calls = sum(row.get("metadata", {}).get("api_called", True) for row in results)
        stopped = sum(bool(row["stopped"]) for row in results)
        actual = (calls, stopped)
        expected = (expected_calls, expected_stopped)
        if actual != expected:
            raise AssertionError(f"{filename}: expected {expected}, got {actual}")
        lines.append(f"PASS {filename}: api_calls={calls} stopped={stopped}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results_directory",
        nargs="?",
        type=Path,
        default=Path(__file__).parent / "results",
    )
    for line in validate(parser.parse_args().results_directory):
        print(line)


if __name__ == "__main__":
    main()

