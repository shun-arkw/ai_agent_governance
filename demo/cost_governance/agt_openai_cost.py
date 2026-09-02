"""Live AGT 4.1.0 CostGuard integration with OpenAI gpt-5-nano."""

from __future__ import annotations

import argparse
import asyncio
import os
from importlib.metadata import version
from pathlib import Path

from agt_budget import AGTBudgetController, AGTBudgetSettings, run_agt_schedule
from common import DEFAULT_TASKS, emit_document, experiment_document, require_live
from openai_runtime import run_openai_task


HERE = Path(__file__).parent


async def run(args: argparse.Namespace) -> None:
    require_live(args.live)
    model = os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-nano")
    settings = AGTBudgetSettings(
        estimated_task_usd=args.estimated_task_usd,
        per_task_limit_usd=args.per_task_limit_usd,
        per_agent_daily_limit_usd=args.per_agent_daily_limit_usd,
        org_monthly_budget_usd=args.org_monthly_budget_usd,
    )
    controller = AGTBudgetController(settings)

    async def execute(task):
        return await run_openai_task(
            task,
            experiment="agt_openai",
            model=model,
            pricing_path=args.pricing,
            max_turns=args.max_turns,
            max_output_tokens=args.max_output_tokens,
        )

    results = await run_agt_schedule(
        tasks=DEFAULT_TASKS,
        controller=controller,
        execute=execute,
        system="agt_openai",
        sdk_version=version("openai-agents"),
        model=model,
        experiment="agt_openai",
    )
    emit_document(
        experiment_document(
            name="agt_openai",
            results=results,
            metadata={
                "agt_version": version("agent-governance-toolkit"),
                "agt_summary": controller.summary(),
                "integration_limit": (
                    "Sequential check_task then record_cost; actual cost can overshoot the estimate."
                ),
            },
        ),
        args.output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--estimated-task-usd", type=float, default=0.005)
    parser.add_argument("--per-task-limit-usd", type=float, default=0.02)
    parser.add_argument("--per-agent-daily-limit-usd", type=float, default=0.04)
    parser.add_argument("--org-monthly-budget-usd", type=float, default=0.08)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--pricing", type=Path, default=HERE / "pricing.json")
    parser.add_argument("--output", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
