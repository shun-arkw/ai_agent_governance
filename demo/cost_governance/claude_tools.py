"""Side-effect-free in-process MCP tool used by Claude cost experiments."""

from __future__ import annotations

from claude_agent_sdk import create_sdk_mcp_server, tool


SERVER_NAME = "cost_steps"
RECORD_STEP_TOOL = f"mcp__{SERVER_NAME}__record_step"


def build_step_server(completed_steps: list[int]):
    """Create an MCP server that records only integer step identifiers."""

    @tool("record_step", "Record one experiment step", {"step": int})
    async def record_step(args: dict) -> dict:
        step = int(args["step"])
        completed_steps.append(step)
        return {"content": [{"type": "text", "text": f"recorded {step}"}]}

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="1.0.0",
        tools=[record_step],
    )
