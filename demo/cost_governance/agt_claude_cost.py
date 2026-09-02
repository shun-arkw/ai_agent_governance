"""Live AGT 4.1.0 CostGuard integration with Claude Haiku."""

from __future__ import annotations

import argparse
import asyncio
import os
from importlib.metadata import version
from pathlib import Path

from agt_budget import AGTBudgetController, AGTBudgetSettings, run_agt_schedule
from claude_runtime import run_claude_task
from common import DEFAULT_TASKS, emit_document, experiment_document, require_live


async def run(args: argparse.Namespace) -> None:
    require_live(args.live)
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    settings = AGTBudgetSettings(
        estimated_task_usd=args.estimated_task_usd,
        per_task_limit_usd=args.per_task_limit_usd,
        per_agent_daily_limit_usd=args.per_agent_daily_limit_usd,
        org_monthly_budget_usd=args.org_monthly_budget_usd,
    )
    controller = AGTBudgetController(settings)

    async def execute(task):
        result = await run_claude_task(
            task,
            experiment="agt_claude",
            model=model,
            max_turns=args.max_turns,
            max_budget_usd=args.claude_task_budget_usd,
        )
        if result.reported_cost_usd is None:
            raise RuntimeError(
                "Claude returned no total_cost_usd; refusing to record an unknown cost in AGT"
            )
        return result

    results = await run_agt_schedule(
        tasks=DEFAULT_TASKS,
        controller=controller,
        execute=execute,
        system="agt_claude",
        sdk_version=version("claude-agent-sdk"),
        model=model,
        experiment="agt_claude",
    )
    emit_document(
        experiment_document(
            name="agt_claude",
            results=results,
            metadata={
                "agt_version": version("agent-governance-toolkit"),
                "agt_summary": controller.summary(),
                "budget_layers": {
                    "claude_run": args.claude_task_budget_usd,
                    "agt_cross_task": settings.to_dict(),
                },
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
    parser.add_argument("--claude-task-budget-usd", type=float, default=0.02)
    parser.add_argument("--max-turns", type=int, default=3)
    parser.add_argument("--output", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
