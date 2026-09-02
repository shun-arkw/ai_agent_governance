"""Reusable OpenAI Agents SDK runtime for the cost experiments."""

from __future__ import annotations

import copy
import os
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agents import Agent, ModelSettings, RunConfig, RunHooks, Runner, function_tool
from agents.exceptions import MaxTurnsExceeded
from openai.types.shared_params import Reasoning

from common import (
    TaskResult,
    TaskSpec,
    UsageData,
    calculate_openai_cost,
    load_pricing,
    task_prompt,
)


class UsageCaptureHooks(RunHooks):
    """Keep the latest usage snapshot even if the Runner raises on a limit."""

    def __init__(self) -> None:
        self.usage: Any = None

    async def on_llm_end(self, context, _agent, _response) -> None:
        self.usage = copy.deepcopy(context.usage)


def _usage_data(usage: Any) -> UsageData:
    if usage is None:
        return UsageData()
    entries = []
    for entry in usage.request_usage_entries:
        dump = getattr(entry, "model_dump", None)
        entries.append(dump(mode="json") if callable(dump) else str(entry))
    return UsageData(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        raw={"request_usage_entries": entries},
    )


async def run_openai_task(
    task: TaskSpec,
    *,
    experiment: str,
    model: str,
    pricing_path: Path,
    max_turns: int,
    max_output_tokens: int,
) -> TaskResult:
    """Execute one paid OpenAI task and return provider-neutral measurements."""

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")

    completed_steps: list[int] = []

    @function_tool
    def record_step(step: int) -> str:
        """Record one integer experiment step."""

        completed_steps.append(step)
        return f"recorded {step}"

    agent = Agent(
        name=f"cost-experiment-{task.agent_id}",
        model=model,
        model_settings=ModelSettings(
            max_tokens=max_output_tokens,
            reasoning=Reasoning(effort="minimal"),
            verbosity="low",
            parallel_tool_calls=False,
        ),
        instructions="Call the requested tool exactly once and keep the final answer minimal.",
        tools=[record_step],
    )
    hooks = UsageCaptureHooks()
    stopped = False
    stop_reason = "completed"
    final_output: str | None = None
    try:
        result = await Runner.run(
            agent,
            task_prompt(task.step),
            max_turns=max_turns,
            hooks=hooks,
            run_config=RunConfig(tracing_disabled=True),
        )
        hooks.usage = result.context_wrapper.usage
        final_output = str(result.final_output)
    except MaxTurnsExceeded:
        stopped = True
        stop_reason = "max_turns_exceeded"

    usage = _usage_data(hooks.usage)
    pricing = load_pricing(pricing_path, model)
    calculated_cost = calculate_openai_cost(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        pricing=pricing,
    )
    return TaskResult(
        system="openai_agents_sdk",
        sdk_version=version("openai-agents"),
        model=model,
        experiment=experiment,
        organization_id=task.organization_id,
        agent_id=task.agent_id,
        task_id=task.task_id,
        usage=usage,
        calculated_cost_usd=calculated_cost,
        cost_source="application_calculation_from_openai_usage",
        completed_steps=completed_steps,
        stopped=stopped,
        stop_reason=stop_reason,
        budget={
            "native_usd_budget": False,
            "max_turns": max_turns,
            "max_output_tokens": max_output_tokens,
        },
        metadata={
            "final_output": final_output,
            "pricing": pricing,
            "cost_is_estimate": True,
        },
    )
