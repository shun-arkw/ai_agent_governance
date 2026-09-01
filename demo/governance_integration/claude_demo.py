"""Claude Agent SDK 0.2.144固有機能だけを使うガバナンスデモ。

自作のインプロセスMCP Tool要求を ``can_use_tool`` で検査する。Policy条件は
Pythonコードへ直接実装しており、AGTは使用しない。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

from common import (
    OPERATIONS_PROMPT,
    print_workspace_result,
    seed_workspace,
    verify_workspace_result,
)
from claude_file_tools import (
    DELETE_TOOL,
    READ_TOOL,
    SERVER_NAME,
    TOOL_NAMES,
    WRITE_TOOL,
    build_file_server,
)


def referenced_filename(tool_name: str, input_data: dict[str, Any]) -> str | None:
    """自作MCP Toolの共通filename引数から対象名を取り出す。"""
    if tool_name in TOOL_NAMES:
        filename = input_data.get("filename")
        return filename if isinstance(filename, str) else None
    return None


async def run(approve_important_write: bool) -> None:
    """Claude Code Agent loopを起動し、SDK固有Permissionを検証する。"""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required")
    if not os.getenv("ANTHROPIC_WORKSPACE_ID"):
        raise SystemExit("ANTHROPIC_WORKSPACE_ID is required for this API key")

    events: list[str] = []

    async def can_use_tool(tool_name: str, input_data: dict[str, Any], _context):
        """Claude SDKから届く権限確認要求へ許可／拒否を返すコールバック。"""
        filename = referenced_filename(tool_name, input_data)
        if tool_name == READ_TOOL and filename in {"normal.txt", "important.txt"}:
            events.append(f"ALLOW read_file {filename}")
            return PermissionResultAllow(updated_input=input_data)
        if tool_name == WRITE_TOOL and filename == "normal.txt":
            events.append("ALLOW write_file normal.txt")
            return PermissionResultAllow(updated_input=input_data)
        if tool_name == WRITE_TOOL and filename == "important.txt":
            events.append("APPROVAL_REQUIRED write_file important.txt")
            if approve_important_write:
                events.append("APPROVED write_file important.txt")
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(
                message="Human reviewer rejected writing important.txt. Do not retry."
            )
        if tool_name == DELETE_TOOL and filename == "normal.txt":
            events.append("ALLOW delete_file normal.txt")
            return PermissionResultAllow(updated_input=input_data)
        if tool_name == DELETE_TOOL and filename == "important.txt":
            events.append("DENY delete_file important.txt")
            return PermissionResultDeny(
                message="Governance policy denied deletion of important.txt. Do not retry."
            )
        events.append(f"DENY {tool_name} unsupported-input")
        return PermissionResultDeny(message="Only the five requested demo operations are allowed.")

    # OpenAI版と同じ3操作を、自作のインプロセスMCP ToolとしてClaudeへ渡す。
    with tempfile.TemporaryDirectory(prefix="claude-governance-demo-") as directory:
        workspace = Path(directory)
        seed_workspace(workspace)
        file_server = build_file_server(workspace)
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        # Claude Agent SDKではAgent classを明示的に生成せず、Optionsとquery()の
        # 組合せでClaude CodeのAgent loopを構成・実行する。
        options = ClaudeAgentOptions(
            model=model,
            cwd=workspace,
            tools=TOOL_NAMES,
            mcp_servers={SERVER_NAME: file_server},
            strict_mcp_config=True,
            permission_mode="default",
            # 設定ファイル由来の許可規則を読み込まず、allowed_toolsも指定しないため、
            # 自作MCPツールの権限確認はcan_use_tool()へ送られる。
            can_use_tool=can_use_tool,
            setting_sources=[],
            env={
                "ANTHROPIC_CUSTOM_HEADERS": (
                    f"anthropic-workspace-id: {os.environ['ANTHROPIC_WORKSPACE_ID']}"
                )
            },
            max_turns=12,
            max_budget_usd=0.10,
            effort="low",
            system_prompt=(
                "Follow the requested operation list exactly. Use the file MCP tools. "
                "Never simulate operations in text and never retry a denied operation. "
                "Execute one tool at a time and wait for its result before the next tool."
            ),
        )

        final_result: ResultMessage | None = None
        # query()がモデル呼び出しとTool利用を含むAgent loopを開始する。
        async for message in query(prompt=OPERATIONS_PROMPT, options=options):
            if isinstance(message, ResultMessage):
                final_result = message

        print(f"model={model}")
        print("governance events:")
        for event in events:
            print(f"  {event}")
        print("workspace after run:")
        print_workspace_result(workspace)
        if final_result:
            print(f"agent summary: {final_result.result}")
            print(f"estimated cost: ${final_result.total_cost_usd or 0:.6f}")

        verify_workspace_result(workspace, approve_important_write)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-important-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.approve_important_write))


if __name__ == "__main__":
    main()
