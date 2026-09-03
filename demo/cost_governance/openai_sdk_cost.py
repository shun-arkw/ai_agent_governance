"""Live cost experiment using only OpenAI Agents SDK governance controls."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from common import DEFAULT_TASKS, emit_document, experiment_document, require_live
from openai_runtime import run_openai_task


HERE = Path(__file__).parent


async def run(args: argparse.Namespace) -> None:
    require_live(args.live)
    model = args.model or os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-nano")
    result = await run_openai_task(
        DEFAULT_TASKS[0],
        experiment="openai_sdk_only",
        model=model,
        pricing_path=args.pricing,
        max_turns=args.max_turns,
        max_output_tokens=args.max_output_tokens,
    )
    emit_document(
        experiment_document(name="openai_sdk_only", results=[result]),
        args.output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", help="OpenAI model ID (defaults to OPENAI_DEFAULT_MODEL)")
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--pricing", type=Path, default=HERE / "pricing.json")
    parser.add_argument("--output", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
