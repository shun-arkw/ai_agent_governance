"""OpenAI Agents SDK 0.22.0固有機能だけを使うガバナンスデモ。

Policy条件はPythonコード内の ``needs_approval`` とTool Input Guardrailへ
直接実装する。AGTは使用しない。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
from agents.run import RunResult
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    tool_input_guardrail,
)

from common import (
    OPERATIONS_PROMPT,
    print_workspace_result,
    safe_file,
    seed_workspace,
    verify_workspace_result,
)


def build_agent(workspace: Path, events: list[str]) -> Agent:
    """Function ToolとSDK固有Policyを持つOpenAI Agentを構築する。"""

    # OpenAI版では、このデモプログラムがFunction Tool本体を定義してSDKへ登録する。
    @function_tool
    def read_file(filename: str) -> str:
        """デモWorkspaceのUTF-8ファイルを読み込む。"""
        content = safe_file(workspace, filename).read_text(encoding="utf-8")
        events.append(f"ALLOW read_file {filename}")
        return content

    async def important_write_needs_approval(_ctx, params: dict, _call_id: str) -> bool:
        """important.txtへのWriteだけSDKの承認中断を要求する。"""
        needs_approval = params.get("filename") == "important.txt"
        if needs_approval:
            events.append("APPROVAL_REQUIRED write_file important.txt")
        return needs_approval

    @function_tool(needs_approval=important_write_needs_approval)
    def write_file(filename: str, content: str) -> str:
        """デモWorkspaceのUTF-8ファイルを上書きする。"""
        safe_file(workspace, filename).write_text(content, encoding="utf-8")
        events.append(f"ALLOW write_file {filename}")
        return f"wrote {filename}"

    @tool_input_guardrail
    def protect_important_delete(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        """Tool実行前に引数を検査し、重要ファイルのDeleteを遮断する。"""
        arguments = json.loads(data.context.tool_arguments)
        filename = arguments.get("filename")
        if filename == "important.txt":
            events.append("DENY delete_file important.txt")
            return ToolGuardrailFunctionOutput.reject_content(
                "Governance policy denied deletion of important.txt. Do not retry.",
                output_info={"decision": "deny", "resource": filename},
            )
        return ToolGuardrailFunctionOutput.allow({"decision": "allow", "resource": filename})

    @function_tool(tool_input_guardrails=[protect_important_delete])
    def delete_file(filename: str) -> str:
        """デモWorkspaceからファイルを削除する。"""
        safe_file(workspace, filename).unlink()
        events.append(f"ALLOW delete_file {filename}")
        return f"deleted {filename}"

    # AgentへToolとモデルを登録する。Policy条件もこのbuild_agent内にあるため、
    # この版はOpenAI Agents SDK固有のガバナンス実装となる。
    return Agent(
        name="OpenAI file governance demo",
        model=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-nano"),
        model_settings=ModelSettings(max_tokens=2000, verbosity="low", parallel_tool_calls=True),
        instructions=(
            "Follow the requested operation list exactly. Always call the tools; never simulate "
            "file operations in text. All five operations are independent: a rejected operation "
            "must not stop later operations. Respect SDK approval and guardrail results."
        ),
        tools=[read_file, write_file, delete_file],
    )


async def resolve_approvals(agent: Agent, result: RunResult, approve: bool) -> RunResult:
    """中断されたTool callを承認／拒否し、同じRunStateから処理を再開する。"""
    while result.interruptions:
        state = result.to_state()
        for interruption in result.interruptions:
            if approve:
                state.approve(interruption)
            else:
                state.reject(
                    interruption,
                    rejection_message="Human reviewer rejected writing important.txt. Do not retry.",
                )
        result = await Runner.run(agent, state, max_turns=12)
    return result


async def run(approve_important_write: bool) -> None:
    """一時WorkspaceでAgentを実行し、イベントと実ファイル状態を検証する。"""
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")
    events: list[str] = []
    # 実Repositoryを誤って変更しないよう、全Tool操作を一時Directoryへ隔離する。
    with tempfile.TemporaryDirectory(prefix="openai-governance-demo-") as directory:
        workspace = Path(directory)
        seed_workspace(workspace)
        agent = build_agent(workspace, events)
        result = await Runner.run(
            agent,
            OPERATIONS_PROMPT,
            max_turns=12,
            run_config=RunConfig(tracing_disabled=True),
        )
        result = await resolve_approvals(agent, result, approve_important_write)

        print(f"model={agent.model}")
        print("governance events:")
        for event in events:
            print(f"  {event}")
        print("workspace after run:")
        print_workspace_result(workspace)
        print(f"agent summary: {result.final_output}")

        # モデルの文章ではなく、実際の副作用がPolicyどおりだったか検証する。
        verify_workspace_result(workspace, approve_important_write)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-important-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.approve_important_write))


if __name__ == "__main__":
    main()
