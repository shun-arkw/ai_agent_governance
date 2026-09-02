"""Adapter between real provider task results and AGT 4.1.0 CostGuard."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Awaitable, Callable

warnings.filterwarnings(
    "ignore",
    message="agentmesh-platform is deprecated.*",
    category=DeprecationWarning,
)
from agent_sre.cost.guard import CostGuard  # noqa: E402

from common import TaskResult, TaskSpec


@dataclass(frozen=True)
class AGTBudgetSettings:
    estimated_task_usd: float
    per_task_limit_usd: float
    per_agent_daily_limit_usd: float
    org_monthly_budget_usd: float

    def to_dict(self) -> dict[str, float | str | bool]:
        return {
            "enforcement": "AGT CostGuard check_task before each API task",
            "estimated_task_usd": self.estimated_task_usd,
            "per_task_limit_usd": self.per_task_limit_usd,
            "per_agent_daily_limit_usd": self.per_agent_daily_limit_usd,
            "org_monthly_budget_usd": self.org_monthly_budget_usd,
            "concurrent_execution_supported": False,
        }


class AGTBudgetController:
    """Sequential real-cost integration for AGT's advisory pre-check API.

    ``check_task`` uses a conservative estimate before a paid call. The actual
    provider cost is recorded afterward. AGT 4.1.0 has no reservation
    reconciliation API, so this adapter intentionally runs tasks sequentially.
    """

    def __init__(self, settings: AGTBudgetSettings) -> None:
        self.settings = settings
        self.guard = CostGuard(
            per_task_limit=settings.per_task_limit_usd,
            per_agent_daily_limit=settings.per_agent_daily_limit_usd,
            org_monthly_budget=settings.org_monthly_budget_usd,
            anomaly_detection=False,
            auto_throttle=False,
        )

    def precheck(self, task: TaskSpec) -> tuple[bool, str]:
        return self.guard.check_task(task.agent_id, self.settings.estimated_task_usd)

    def record(self, result: TaskResult) -> None:
        actual_cost = result.effective_cost_usd
        alerts = self.guard.record_cost(
            agent_id=result.agent_id,
            task_id=result.task_id,
            cost_usd=actual_cost,
            breakdown={"provider_task_cost": actual_cost},
        )
        result.budget.update(self.settings.to_dict())
        result.metadata["agt_post_charge_alerts"] = [alert.to_dict() for alert in alerts]
        result.metadata["agt_actual_minus_estimate_usd"] = (
            actual_cost - self.settings.estimated_task_usd
        )

    def denied_result(
        self,
        task: TaskSpec,
        *,
        system: str,
        sdk_version: str,
        model: str,
        experiment: str,
        reason: str,
    ) -> TaskResult:
        return TaskResult(
            system=system,
            sdk_version=sdk_version,
            model=model,
            experiment=experiment,
            organization_id=task.organization_id,
            agent_id=task.agent_id,
            task_id=task.task_id,
            stopped=True,
            stop_reason=f"agt_precheck_denied: {reason}",
            budget=self.settings.to_dict(),
            metadata={"api_called": False},
        )

    def summary(self) -> dict:
        return self.guard.summary()


async def run_agt_schedule(
    *,
    tasks: tuple[TaskSpec, ...],
    controller: AGTBudgetController,
    execute: Callable[[TaskSpec], Awaitable[TaskResult]],
    system: str,
    sdk_version: str,
    model: str,
    experiment: str,
) -> list[TaskResult]:
    """Run real API tasks sequentially, gating every task through AGT."""

    organizations = {task.organization_id for task in tasks}
    if len(organizations) != 1:
        raise ValueError("One CostGuard instance represents exactly one organization")

    results: list[TaskResult] = []
    for task in tasks:
        allowed, reason = controller.precheck(task)
        if not allowed:
            results.append(
                controller.denied_result(
                    task,
                    system=system,
                    sdk_version=sdk_version,
                    model=model,
                    experiment=experiment,
                    reason=reason,
                )
            )
            continue

        result = await execute(task)
        result.system = system
        result.experiment = experiment
        result.metadata["api_called"] = True
        result.metadata["agt_precheck_reason"] = reason
        controller.record(result)
        results.append(result)
    return results

