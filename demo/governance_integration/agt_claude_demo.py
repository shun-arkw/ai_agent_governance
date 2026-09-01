"""AGT 4.1.0とClaudeの実行基盤を組み合わせた、実モデルによるデモ。

エージェントループにはClaude Agent SDKを使用し、ファイル操作には独自に実装した
インプロセスMCPツールを使用する。ツール呼び出しを共通形式に正規化し、AGTのYAML
ポリシーによる判定を ``can_use_tool`` の許可／拒否へ変換する。

AGTとの連携フロー::

    1. ユーザーのプロンプトをClaude Haikuへ送る

    2. Claude Haikuが、例えば次のMCPツール呼び出しを生成する
       tool_name = "mcp__files__write_file"
       input_data = {"filename": "important.txt", "content": "..."}

    3. Claude Agent SDKはツール本体を実行する前に、このデモプログラムが
       can_use_toolに登録したagt_can_use_tool()を呼び出す
       agt_can_use_tool()はAGTが提供する関数ではなく、このデモプログラムが定義する
       「Claude Agent SDKとAGTを接続するアダプターコールバック」である

    4. agt_can_use_tool()はClaude固有のツール名をAGT共通のアクションへ変換する
       "mcp__files__write_file" → "write_file"

    5. evaluate()を介してAGTのPolicyEngine.evaluate()を呼び出す
       context = {
           "action": {"type": "write_file"},
           "resource": {"name": "important.txt"},
       }

    6. AGTはpolicy/file_policy.yamlを評価し、PolicyDecisionを返す
       この例ではaction="require_approval"

    7. agt_can_use_tool()がAGTの判定をClaude SDK用の戻り値へ変換する
       承認済み → PermissionResultAllow
       未承認／deny → PermissionResultDeny

    8. Claude Agent SDKはPermissionResultAllowの場合にのみMCPツール本体を実行する

番号付きの ``AGT連携 1〜5`` コメントが、上記フローの実装箇所を示す。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

warnings.filterwarnings(
    "ignore",
    message="agentmesh-platform is deprecated.*",
    category=DeprecationWarning,
)
from agentmesh.governance.policy import PolicyDecision, PolicyEngine  # noqa: E402

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


AGENT_DID = "did:example:file-demo-agent"
# AGT連携 1: OpenAI版と共有するポリシーファイル。制限条件はこのYAMLに集約する。
POLICY_PATH = Path(__file__).parent / "policy" / "file_policy.yaml"


def build_engine() -> PolicyEngine:
    """OpenAI版と同じYAMLを読み込み、AGT Policy Engineを生成する。

    Claude SDKへポリシーを直接渡すのではなく、このデモプログラム内で
    AGT Engineを構築し、後述の権限確認コールバックから問い合わせる。
    """
    # AGT連携 2: 共通YAMLをAGT PolicyEngineへ登録する。
    engine = PolicyEngine(conflict_strategy="deny_overrides")
    engine.load_yaml_file(str(POLICY_PATH))
    return engine


def evaluate(engine: PolicyEngine, operation: str, filename: str) -> PolicyDecision:
    """正規化済みのアクションとリソースをAGTのpre_toolステージで評価する。

    この関数が、Claude SDK側のツール呼び出しとAGT Policy Engineを橋渡しする。
    """
    # AGT連携 3: ツールの実行前に、正規化したアクションとリソースをAGTへ渡す。
    return engine.evaluate(
        agent_did=AGENT_DID,
        stage="pre_tool",
        context={
            "action": {"type": operation},
            "resource": {"name": filename},
        },
    )


def normalize_tool_call(tool_name: str, input_data: dict[str, Any]) -> tuple[str, str]:
    """MCPツール名からプレフィックスを除き、AGT用のアクションへ正規化する。

    Claudeが返すツール名は ``mcp__files__read_file`` 形式だが、共通YAMLでは
    ``read_file`` を評価する。この形式の違いをSDKアダプターが吸収する。
    ファイル名は書き換えず、MCPツールへ渡す値と同じ値をポリシーで評価する。
    """
    action_by_tool = {
        READ_TOOL: "read_file",
        WRITE_TOOL: "write_file",
        DELETE_TOOL: "delete_file",
    }
    operation = action_by_tool.get(tool_name, "unsupported")
    raw_filename = input_data.get("filename")
    filename = raw_filename if isinstance(raw_filename, str) else ""
    return operation, filename


async def run(approve_important_write: bool) -> None:
    """AGTの判定を権限情報へ変換し、Claudeのエージェントループを実行する。"""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required")
    if not os.getenv("ANTHROPIC_WORKSPACE_ID"):
        raise SystemExit("ANTHROPIC_WORKSPACE_ID is required for this API key")

    engine = build_engine()
    events: list[str] = []

    async def agt_can_use_tool(tool_name: str, input_data: dict[str, Any], _context):
        """Claude SDKが権限確認を求めたツール呼び出しをAGTで評価するゲートウェイ。

        この関数はAGTのAPIではなく、このデモプログラム独自のアダプターである。
        後で ``ClaudeAgentOptions(can_use_tool=agt_can_use_tool)`` と登録することで、
        Claude Agent SDKがMCPツールを実行する直前に自動的に呼び出す。

        Claude Agent SDKから受け取る値:
            tool_name:
                モデルが選択したツール名。例: ``mcp__files__write_file``。
            input_data:
                モデルが生成したTool引数。例:
                ``{"filename": "important.txt", "content": "..."}``。
            _context:
                Claude SDKの権限確認コンテキスト。今回は使用しないため名前に_を付ける。

        この関数が行う処理:
            1. Claude固有のツール名をread_file/write_file/delete_fileへ正規化する。
            2. アクションとリソースをAGT PolicyEngineへ渡す。
            3. AGTのallow/require_approval/denyをClaudeの権限情報へ変換する。

        Claude Agent SDKへ返す値:
            PermissionResultAllow:
                SDKは独自に実装したMCPツール本体を実行する。
            PermissionResultDeny:
                SDKはツール本体を実行せず、拒否理由をモデルへ返す。

        important.txtなどの個別のポリシー条件はここに書かず、
        policy/file_policy.yamlに置く。
        """
        # AGT連携 4-A: Claude SDKから受け取ったツール呼び出しを共通形式へ変換する。
        operation, filename = normalize_tool_call(tool_name, input_data)

        # AGT連携 4-B: ツール本体を実行する前に、AGTへポリシー評価を依頼する。
        decision = evaluate(engine, operation, filename)
        events.append(
            f"{decision.action.upper()} {operation} {filename or '<none>'} "
            f"policy={decision.policy_name} rule={decision.matched_rule}"
        )

        # AGT連携 5: AGTの抽象的な判定をClaude SDKのPermissionResultへ変換する。
        # Claude Agent SDKはこの戻り値に基づいて、ツールを実行するか判断する。
        # allowの場合にのみツールの実行を許可する。
        if decision.action == "allow":
            return PermissionResultAllow(updated_input=input_data)
        if decision.action == "require_approval" and approve_important_write:
            events.append(f"APPROVED {operation} {filename}")
            return PermissionResultAllow(updated_input=input_data)
        if decision.action == "require_approval":
            # AGTは承認の要否を判定する。このデモではCLIフラグで人間の判断を代用する。
            return PermissionResultDeny(
                message="AGT required approval; reviewer rejected the request. Do not retry."
            )
        return PermissionResultDeny(
            message=f"AGT denied {operation} on {filename}. Do not retry."
        )

    # 独自MCPツールが操作できるワークスペースを一時ディレクトリ内に限定する。
    with tempfile.TemporaryDirectory(prefix="agt-claude-demo-") as directory:
        workspace = Path(directory)
        seed_workspace(workspace)
        file_server = build_file_server(workspace)
        model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        # Claude版ではAgentオブジェクトを直接生成せず、Optionsとquery()でループを構成する。
        options = ClaudeAgentOptions(
            model=model,
            cwd=workspace,
            tools=TOOL_NAMES,
            mcp_servers={SERVER_NAME: file_server},
            strict_mcp_config=True,
            permission_mode="default",
            # 重要な接続点:
            # ここで独自のアダプターコールバックをClaude Agent SDKへ登録する。
            # この構成では設定ファイル由来の許可規則を読み込まず、allowed_toolsも
            # 指定しないため、MCPツール本体より先にagt_can_use_tool()へ権限確認が届く。
            can_use_tool=agt_can_use_tool,
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
                "Follow all five operations exactly with the file MCP tools. Execute one "
                "tool at a time. Continue after rejection. AGT decisions are authoritative."
            ),
        )

        final_result: ResultMessage | None = None
        # query()がClaudeモデルと独自MCPツールを使うエージェントループを開始する。
        async for message in query(prompt=OPERATIONS_PROMPT, options=options):
            if isinstance(message, ResultMessage):
                final_result = message

        print(f"runtime=Claude Agent SDK model={model}")
        print(f"governance=AGT 4.1.0 policy={POLICY_PATH.name}")
        print("governance events:")
        for event in events:
            print(f"  {event}")
        print("workspace after run:")
        print_workspace_result(workspace)
        if final_result:
            print(f"agent summary (not authoritative): {final_result.result}")
            print(f"estimated cost: ${final_result.total_cost_usd or 0:.6f}")

        # AGTイベントと実際のファイルシステムの状態を正とし、モデルの要約には依存しない。
        verify_workspace_result(workspace, approve_important_write)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-important-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.approve_important_write))


if __name__ == "__main__":
    main()
