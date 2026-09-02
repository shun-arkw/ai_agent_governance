"""Cost governance experiments shared data structures and utilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskSpec:
    """One API-backed task and its logical governance identifiers."""

    organization_id: str
    agent_id: str
    task_id: str
    step: int


DEFAULT_TASKS = (
    TaskSpec("org-demo", "agent-a", "task-a-1", 1),
    TaskSpec("org-demo", "agent-a", "task-a-2", 2),
    TaskSpec("org-demo", "agent-b", "task-b-1", 3),
    TaskSpec("org-demo", "agent-b", "task-b-2", 4),
)


@dataclass
class UsageData:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    raw: dict[str, Any] | None = None


@dataclass
class TaskResult:
    """Provider-neutral result emitted by every experiment."""

    system: str
    sdk_version: str
    model: str
    experiment: str
    organization_id: str
    agent_id: str
    task_id: str
    usage: UsageData = field(default_factory=UsageData)
    reported_cost_usd: float | None = None
    calculated_cost_usd: float | None = None
    cost_source: str | None = None
    completed_steps: list[int] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str = "completed"
    budget: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_cost_usd(self) -> float:
        if self.reported_cost_usd is not None:
            return self.reported_cost_usd
        return self.calculated_cost_usd or 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def task_prompt(step: int) -> str:
    """Return a short prompt that reliably creates one tool turn."""

    return (
        f"Call record_step exactly once with step={step}. "
        "Wait for the tool result, then reply with only: done"
    )


def load_pricing(path: Path, model: str) -> dict[str, Any]:
    """Load a pinned per-million-token price entry."""

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return data["models"][model]
    except KeyError as exc:
        raise ValueError(f"No pinned pricing entry for model {model!r} in {path}") from exc


def calculate_openai_cost(
    *, input_tokens: int, output_tokens: int, pricing: dict[str, Any]
) -> float:
    """Calculate an application-side estimate from uncached token totals."""

    input_cost = input_tokens * float(pricing["input_usd_per_million"]) / 1_000_000
    output_cost = output_tokens * float(pricing["output_usd_per_million"]) / 1_000_000
    return input_cost + output_cost


def experiment_document(
    *, name: str, results: list[TaskResult], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build the JSON document written by live experiments."""

    return {
        "schema_version": 1,
        "experiment": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "results": [result.to_dict() for result in results],
        "total_effective_cost_usd": sum(result.effective_cost_usd for result in results),
    }


def emit_document(document: dict[str, Any], output: Path | None) -> None:
    """Print a result and optionally write it to an explicitly selected path."""

    rendered = json.dumps(document, ensure_ascii=False, indent=2)
    print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")


def require_live(live: bool) -> None:
    """Prevent an accidental paid API invocation."""

    if not live:
        raise SystemExit("Paid API calls are disabled. Re-run with --live after reviewing settings.")

