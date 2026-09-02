"""Live cost experiment using Claude Agent SDK native budget controls."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from claude_runtime import run_claude_task
from common import DEFAULT_TASKS, emit_document, experiment_document, require_live


async def run(args: argparse.Namespace) -> None:
    require_live(args.live)
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    result = await run_claude_task(
        DEFAULT_TASKS[0],
        experiment="claude_sdk_only",
        model=model,
        max_turns=args.max_turns,
        max_budget_usd=args.max_budget_usd,
    )
    emit_document(
        experiment_document(name="claude_sdk_only", results=[result]),
        args.output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-budget-usd", type=float, default=0.02)
    parser.add_argument("--output", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
