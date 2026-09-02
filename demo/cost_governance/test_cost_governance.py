"""Offline tests for the real-API cost governance adapters."""

from __future__ import annotations

import asyncio
from pathlib import Path
import unittest

from agt_budget import AGTBudgetController, AGTBudgetSettings, run_agt_schedule
from compare_results import markdown, summarize
from common import (
    TaskResult,
    TaskSpec,
    UsageData,
    calculate_openai_cost,
    experiment_document,
    load_pricing,
    require_live,
)


HERE = Path(__file__).parent


def _result(task: TaskSpec, cost: float) -> TaskResult:
    return TaskResult(
        system="fake-provider",
        sdk_version="test",
        model="test-model",
        experiment="test",
        organization_id=task.organization_id,
        agent_id=task.agent_id,
        task_id=task.task_id,
        usage=UsageData(total_tokens=10),
        reported_cost_usd=cost,
        cost_source="offline-test",
        completed_steps=[task.step],
    )


class CostGovernanceTests(unittest.TestCase):
    def test_pinned_openai_cost_calculation(self) -> None:
        pricing = load_pricing(HERE / "pricing.json", "gpt-5-nano")
        cost = calculate_openai_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            pricing=pricing,
        )
        self.assertAlmostEqual(cost, 0.45)

    def test_live_flag_is_required(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--live"):
            require_live(False)

    def test_agt_agent_limit_denies_before_provider_call(self) -> None:
        tasks = (
            TaskSpec("org", "agent-a", "a-1", 1),
            TaskSpec("org", "agent-a", "a-2", 2),
            TaskSpec("org", "agent-b", "b-1", 3),
        )
        controller = AGTBudgetController(
            AGTBudgetSettings(
                estimated_task_usd=0.003,
                per_task_limit_usd=0.01,
                per_agent_daily_limit_usd=0.005,
                org_monthly_budget_usd=0.02,
            )
        )
        called: list[str] = []

        async def execute(task: TaskSpec) -> TaskResult:
            called.append(task.task_id)
            return _result(task, 0.004)

        results = asyncio.run(
            run_agt_schedule(
                tasks=tasks,
                controller=controller,
                execute=execute,
                system="agt-test",
                sdk_version="test",
                model="test-model",
                experiment="test",
            )
        )

        self.assertEqual(called, ["a-1", "b-1"])
        self.assertTrue(results[1].stopped)
        self.assertFalse(results[1].metadata["api_called"])
        self.assertIn("daily budget", results[1].stop_reason)
        self.assertEqual(
            controller.summary()["agents"]["agent-a"]["spent_today_usd"],
            0.004,
        )

    def test_agt_org_limit_denies_other_agent_before_provider_call(self) -> None:
        tasks = (
            TaskSpec("org", "agent-a", "a-1", 1),
            TaskSpec("org", "agent-b", "b-1", 2),
        )
        controller = AGTBudgetController(
            AGTBudgetSettings(
                estimated_task_usd=0.003,
                per_task_limit_usd=0.01,
                per_agent_daily_limit_usd=0.02,
                org_monthly_budget_usd=0.005,
            )
        )
        called: list[str] = []

        async def execute(task: TaskSpec) -> TaskResult:
            called.append(task.task_id)
            return _result(task, 0.004)

        results = asyncio.run(
            run_agt_schedule(
                tasks=tasks,
                controller=controller,
                execute=execute,
                system="agt-test",
                sdk_version="test",
                model="test-model",
                experiment="test",
            )
        )

        self.assertEqual(called, ["a-1"])
        self.assertIn("org monthly budget", results[1].stop_reason)

    def test_agt_per_task_limit_can_block_every_paid_call(self) -> None:
        task = TaskSpec("org", "agent-a", "a-1", 1)
        controller = AGTBudgetController(
            AGTBudgetSettings(
                estimated_task_usd=0.02,
                per_task_limit_usd=0.01,
                per_agent_daily_limit_usd=1.0,
                org_monthly_budget_usd=1.0,
            )
        )
        called = False

        async def execute(spec: TaskSpec) -> TaskResult:
            nonlocal called
            called = True
            return _result(spec, 0.001)

        results = asyncio.run(
            run_agt_schedule(
                tasks=(task,),
                controller=controller,
                execute=execute,
                system="agt-test",
                sdk_version="test",
                model="test-model",
                experiment="test",
            )
        )

        self.assertFalse(called)
        self.assertTrue(results[0].stopped)
        self.assertIn("per-task limit", results[0].stop_reason)

    def test_document_keeps_reported_and_calculated_cost_distinct(self) -> None:
        task = TaskSpec("org", "agent-a", "a-1", 1)
        result = _result(task, 0.004)
        document = experiment_document(name="test", results=[result])
        self.assertEqual(document["results"][0]["reported_cost_usd"], 0.004)
        self.assertIsNone(document["results"][0]["calculated_cost_usd"])
        self.assertAlmostEqual(document["total_effective_cost_usd"], 0.004)

    def test_comparison_counts_agt_precheck_denials_as_no_api_call(self) -> None:
        task = TaskSpec("org", "agent-a", "a-1", 1)
        called = _result(task, 0.004)
        denied = _result(TaskSpec("org", "agent-a", "a-2", 2), 0.0)
        denied.stopped = True
        denied.metadata["api_called"] = False
        document = experiment_document(name="agt-test", results=[called, denied])
        row = summarize(document, Path("result.json"))
        self.assertEqual(row["api_calls"], 1)
        self.assertEqual(row["stopped"], 1)
        self.assertIn("agt-test", markdown([row]))


if __name__ == "__main__":
    unittest.main()
