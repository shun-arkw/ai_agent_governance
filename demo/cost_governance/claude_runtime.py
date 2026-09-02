"""Reusable Claude Agent SDK runtime for the cost experiments."""

from __future__ import annotations

import os
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk._errors import ResultError

from claude_tools import RECORD_STEP_TOOL, SERVER_NAME, build_step_server
from common import TaskResult, TaskSpec, UsageData, task_prompt


def _number(mapping: dict[str, Any], *names: str) -> int:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _result_from_error(error: ResultError) -> ResultMessage:
    """Recover the terminal result payload carried by SDK budget errors."""

    data = error.data
    return ResultMessage(
        subtype=str(data.get("subtype", "error_during_execution")),
        duration_ms=int(data.get("duration_ms", 0)),
        duration_api_ms=int(data.get("duration_api_ms", 0)),
        is_error=True,
        num_turns=int(data.get("num_turns", 0)),
        session_id=str(data.get("session_id", "")),
        stop_reason=data.get("stop_reason"),
        total_cost_usd=data.get("total_cost_usd"),
        usage=data.get("usage"),
        result=data.get("result"),
        structured_output=data.get("structured_output"),
        model_usage=data.get("modelUsage"),
        permission_denials=data.get("permission_denials"),
        errors=data.get("errors"),
        api_error_status=data.get("api_error_status"),
        uuid=data.get("uuid"),
        terminal_reason=data.get("terminal_reason"),
    )


async def run_claude_task(
    task: TaskSpec,
    *,
    experiment: str,
    model: str,
    max_turns: int,
    max_budget_usd: float,
) -> TaskResult:
    """Execute one paid Claude task and return provider-neutral measurements."""

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required")
    if not os.getenv("ANTHROPIC_WORKSPACE_ID"):
        raise SystemExit("ANTHROPIC_WORKSPACE_ID is required for this API key")

    completed_steps: list[int] = []
    final_result: ResultMessage | None = None
    result_error: ResultError | None = None
    with tempfile.TemporaryDirectory(prefix="claude-cost-experiment-") as directory:
        options = ClaudeAgentOptions(
            model=model,
            cwd=Path(directory),
            tools=[RECORD_STEP_TOOL],
            allowed_tools=[RECORD_STEP_TOOL],
            mcp_servers={SERVER_NAME: build_step_server(completed_steps)},
            strict_mcp_config=True,
            setting_sources=[],
            env={
                "ANTHROPIC_CUSTOM_HEADERS": (
                    f"anthropic-workspace-id: {os.environ['ANTHROPIC_WORKSPACE_ID']}"
                )
            },
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            effort="low",
            system_prompt=(
                "Call the requested record_step tool exactly once and keep the final answer minimal."
            ),
        )
        try:
            async for message in query(prompt=task_prompt(task.step), options=options):
                if isinstance(message, ResultMessage):
                    final_result = message
        except ResultError as error:
            # Claude SDK 0.2.144 raises after emitting a terminal error result
            # (including max_budget_usd). Preserve that result as experiment data.
            result_error = error
            if final_result is None:
                final_result = _result_from_error(error)

    if final_result is None:
        raise RuntimeError("Claude Agent SDK returned no ResultMessage")

    raw_usage = final_result.usage or {}
    input_tokens = _number(raw_usage, "input_tokens", "inputTokens")
    output_tokens = _number(raw_usage, "output_tokens", "outputTokens")
    total_tokens = _number(raw_usage, "total_tokens", "totalTokens") or (
        input_tokens + output_tokens
    )
    stopped = bool(final_result.is_error or final_result.stop_reason not in {None, "end_turn"})
    stop_reason = (
        final_result.terminal_reason
        or final_result.stop_reason
        or ("sdk_error" if final_result.is_error else "completed")
    )
    return TaskResult(
        system="claude_agent_sdk",
        sdk_version=version("claude-agent-sdk"),
        model=model,
        experiment=experiment,
        organization_id=task.organization_id,
        agent_id=task.agent_id,
        task_id=task.task_id,
        usage=UsageData(
            requests=final_result.num_turns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            raw=raw_usage,
        ),
        reported_cost_usd=final_result.total_cost_usd,
        cost_source="claude_agent_sdk_total_cost_usd",
        completed_steps=completed_steps,
        stopped=stopped,
        stop_reason=str(stop_reason),
        budget={
            "native_usd_budget": True,
            "max_budget_usd": max_budget_usd,
            "max_turns": max_turns,
        },
        metadata={
            "final_output": final_result.result,
            "is_error": final_result.is_error,
            "num_turns": final_result.num_turns,
            "total_cost_is_client_side_estimate": True,
            "result_error": str(result_error) if result_error is not None else None,
        },
    )
