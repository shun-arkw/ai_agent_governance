"""AGT 4.1.0とOpenAIの実行基盤を組み合わせた、実モデルによるデモ。

AGTはエージェントランタイムではないため、モデルの呼び出しとツールループには
OpenAI Agents SDKを使用する。ただし、ポリシー条件と判定はAGTの共通YAMLのみから
取得する。OpenAIのガードレール／承認機構は、AGTの判定を実行フローへ反映する
アダプターとして使用する。

AGTとの連携フロー::

    1. ユーザーのプロンプトをgpt-5-nanoへ送る

    2. gpt-5-nanoが、例えば次のFunction Tool呼び出しを生成する
       tool_name = "write_file"
       params = {"filename": "important.txt", "content": "..."}

    3. OpenAI Agents SDKはwrite_fileに登録されたneeds_approvalの判定として、
       agt_write_needs_approval()を呼び出す
       この関数はAGTが提供するものではなく、AGTの判定をOpenAI SDKの承認機構へ
       接続するために、このデモプログラムが定義するアダプターコールバックである

    4. agt_write_needs_approval()がevaluate()を介してAGTの
       PolicyEngine.evaluate()を呼び出す
       context = {
           "action": {"type": "write_file"},
           "resource": {"name": "important.txt"},
       }

    5. AGTはpolicy/file_policy.yamlを評価し、PolicyDecisionを返す
       この例ではaction="require_approval"

    6. agt_write_needs_approval()がrequire_approvalをTrueへ変換する
       OpenAI Runnerはツール本体を実行せず、RunStateを中断して承認を待つ
       resolve_approvals()が拒否または承認をRunStateへ反映し、処理を再開する

    7. 承認済み、または承認不要なツール呼び出しに対して、OpenAI Agents SDKが
       agt_pre_tool_policy()を実行する
       この関数もAGTが提供するものではなく、AGTの判定をOpenAI SDKの
       Tool Input Guardrailへ接続する、このデモ独自のアダプターである

    8. agt_pre_tool_policy()がツール実行直前の状態をAGTで再評価し、
       AGTの判定をOpenAI SDK用の戻り値へ変換する
       deny → ToolGuardrailFunctionOutput.reject_content()
       allow／承認済みのrequire_approval → ToolGuardrailFunctionOutput.allow()

    9. OpenAI Agents SDKはガードレールで拒否されなかった場合にのみ
       Function Tool本体を実行する

番号付きの ``AGT連携 1〜5`` コメントが、上記フローの実装箇所を示す。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
import warnings
from pathlib import Path

from agents import Agent, ModelSettings, RunConfig, Runner, function_tool
from agents.run import RunResult
from agents.tool_guardrails import (
    ToolGuardrailFunctionOutput,
    ToolInputGuardrailData,
    tool_input_guardrail,
)

warnings.filterwarnings(
    "ignore",
    message="agentmesh-platform is deprecated.*",
    category=DeprecationWarning,
)
# AGT 4.1.0が公開するPolicy Engineを、同梱の名前空間からインポートする。
from agentmesh.governance.policy import PolicyDecision, PolicyEngine  # noqa: E402

from common import (
    OPERATIONS_PROMPT,
    print_workspace_result,
    safe_file,
    seed_workspace,
    verify_workspace_result,
)


AGENT_DID = "did:example:file-demo-agent"
# AGT連携 1: OpenAI版とClaude版が共有するポリシーファイルの場所。
# 各操作を許可するか、承認を求めるか、拒否するかはPythonではなく、このYAMLに定義する。
POLICY_PATH = Path(__file__).parent / "policy" / "file_policy.yaml"


def build_engine() -> PolicyEngine:
    """共通YAMLを読み込み、拒否を優先するAGT Policy Engineを生成する。

    ここがAGTポリシーをこのデモプログラムへ読み込む最初の連携点である。
    ``load_yaml_file`` の実行後は、同じengineをすべてのツール呼び出しの評価に再利用する。
    """
    # AGT連携 2: YAML PolicyをAGTの実行可能なPolicyEngineへ登録する。
    engine = PolicyEngine(conflict_strategy="deny_overrides")
    engine.load_yaml_file(str(POLICY_PATH))
    return engine


def evaluate(engine: PolicyEngine, operation: str, filename: str) -> PolicyDecision:
    """ツール名とリソース名をAGTの共通コンテキスト形式へ変換して評価する。

    ``operation`` はread_fileなどのアクション、``filename`` はポリシーが検査する
    リソースを表す。戻り値のPolicyDecisionにはaction、matched_rule、policy_nameなどが
    含まれる。
    """
    # AGT連携 3: SDKから得たツール呼び出しをAGT PolicyEngineで評価する中心部分。
    # stage="pre_tool"のため、実際のファイル操作より前に判定が確定する。
    return engine.evaluate(
        agent_did=AGENT_DID,
        stage="pre_tool",
        context={
            "action": {"type": operation},
            "resource": {"name": filename},
        },
    )


def build_agent(workspace: Path, engine: PolicyEngine, events: list[str]) -> Agent:
    """AGTの判定を適用するFunction Tool群とOpenAI Agentを構築する。"""

    # 承認判定時と実行直前のガードレールで同じアクションを評価する場合があるため、
    # 表示用イベントでは同一の「操作・対象・判定」を重複して記録しない。
    logged: set[tuple[str, str, str]] = set()

    def log_decision(operation: str, filename: str, decision: PolicyDecision) -> None:
        """AGTの判定を、デモ表示用のインメモリイベントとして記録する。"""
        key = (operation, filename, decision.action)
        if key not in logged:
            logged.add(key)
            events.append(
                f"{decision.action.upper()} {operation} {filename} "
                f"policy={decision.policy_name} rule={decision.matched_rule}"
            )

    @tool_input_guardrail
    def agt_pre_tool_policy(data: ToolInputGuardrailData) -> ToolGuardrailFunctionOutput:
        """全Function Toolで共有する、実行直前のAGTポリシーアダプター。

        OpenAI SDKはツール本体を呼び出す直前にこの関数を自動実行する。この関数には
        important.txtなどのポリシー条件を書かず、すべてAGTの判定に従う。
        """
        # SDKが保持するツール名と未加工のJSON引数から、AGT評価用の情報を組み立てる。
        operation = data.context.tool_name
        filename = json.loads(data.context.tool_arguments).get("filename", "")

        # AGT連携 4: 各Function Toolの実行直前に共通のevaluate()を呼び出す。
        decision = evaluate(engine, operation, filename)
        log_decision(operation, filename, decision)

        # AGTのdenyをOpenAI Tool Guardrailの拒否へ変換する。
        # reject_contentを返すと、ツール本体は呼ばれず、拒否理由だけがモデルへ返る。
        if decision.action == "deny":
            return ToolGuardrailFunctionOutput.reject_content(
                f"AGT denied {operation} on {filename}. Do not retry.",
                output_info=decision.model_dump(mode="json"),
            )
        # require_approvalの場合は、このガードレールより前にneeds_approvalで中断される。
        return ToolGuardrailFunctionOutput.allow(decision.model_dump(mode="json"))

    async def agt_write_needs_approval(_ctx, params: dict, _call_id: str) -> bool:
        """AGTのrequire_approvalをOpenAI SDKの承認待ち状態へ変換する。

        Trueを返すと、OpenAI Runnerはツールを実行せずinterruptionsを返す。その後、
        ``resolve_approvals`` が人間による承認／拒否に相当する結果をRunStateへ反映する。
        """
        filename = str(params.get("filename", ""))
        decision = evaluate(engine, "write_file", filename)
        log_decision("write_file", filename, decision)
        # AGT連携 5: AGTの抽象的な判定をOpenAI SDKのbool型の承認要求へ変換する。
        return decision.action == "require_approval"

    # 3つのFunction Toolすべてに同じAGTアダプターを登録する。モデルがどのツールを
    # 選んでも、ツール本体より先にagt_pre_tool_policyが実行される。
    @function_tool(tool_input_guardrails=[agt_pre_tool_policy])
    def read_file(filename: str) -> str:
        """デモWorkspaceのUTF-8ファイルを読み込む。"""
        return safe_file(workspace, filename).read_text(encoding="utf-8")

    @function_tool(
        # write_fileにだけ、AGTのrequire_approvalを扱う承認アダプターも追加する。
        needs_approval=agt_write_needs_approval,
        tool_input_guardrails=[agt_pre_tool_policy],
    )
    def write_file(filename: str, content: str) -> str:
        """デモWorkspaceのUTF-8ファイルを上書きする。"""
        safe_file(workspace, filename).write_text(content, encoding="utf-8")
        return f"wrote {filename}"

    @function_tool(tool_input_guardrails=[agt_pre_tool_policy])
    def delete_file(filename: str) -> str:
        """デモWorkspaceからファイルを削除する。"""
        safe_file(workspace, filename).unlink()
        return f"deleted {filename}"

    # エージェントループ自体はOpenAI SDKが担う。ポリシーの条件分岐はAgentや
    # ツール本体には書かず、上記の共通AGTアダプターへ集約している。
    return Agent(
        name="AGT-governed file agent",
        model=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-nano"),
        model_settings=ModelSettings(max_tokens=2000, verbosity="low", parallel_tool_calls=True),
        instructions=(
            "Follow all five operations exactly and use tools for every operation. Operations are "
            "independent, so continue after rejection. AGT decisions are authoritative."
        ),
        tools=[read_file, write_file, delete_file],
    )


async def resolve_approvals(agent: Agent, result: RunResult, approve: bool) -> RunResult:
    """AGTが要求した承認を解決し、中断したOpenAI RunStateを再開する。

    AGTは「承認が必要」と判定するが、最終的に承認するかどうかは、このデモプログラム
    のようにSDKを利用する側が決定する。
    このデモではCLIの ``--approve-important-write`` で人間の判断を代用する。
    """
    while result.interruptions:
        state = result.to_state()
        for interruption in result.interruptions:
            if approve:
                state.approve(interruption)
            else:
                state.reject(
                    interruption,
                    rejection_message="AGT required approval; reviewer rejected the request.",
                )
        result = await Runner.run(agent, state, max_turns=12)
    return result


async def run(approve_important_write: bool) -> None:
    """一時ワークスペースでAGTとOpenAI Agentを実行し、実際の副作用を検証する。"""
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required")
    events: list[str] = []
    # 実際のリポジトリへ影響を与えないよう、ツールの操作を一時ディレクトリ内に限定する。
    with tempfile.TemporaryDirectory(prefix="agt-openai-demo-") as directory:
        workspace = Path(directory)
        seed_workspace(workspace)
        agent = build_agent(workspace, build_engine(), events)
        result = await Runner.run(
            agent,
            OPERATIONS_PROMPT,
            max_turns=12,
            run_config=RunConfig(tracing_disabled=True),
        )
        result = await resolve_approvals(agent, result, approve_important_write)

        print(f"runtime=OpenAI Agents SDK model={agent.model}")
        print(f"governance=AGT 4.1.0 policy={POLICY_PATH.name}")
        print("governance events:")
        for event in events:
            print(f"  {event}")
        print("workspace after run:")
        print_workspace_result(workspace)
        print(f"agent summary (not authoritative): {result.final_output}")

        # モデルの最終要約は誤る場合があるため、ファイルシステムを直接検証する。
        verify_workspace_result(workspace, approve_important_write)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-important-write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.approve_important_write))


if __name__ == "__main__":
    main()
