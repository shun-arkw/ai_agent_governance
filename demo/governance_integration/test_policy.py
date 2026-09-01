"""共通ポリシーとデモ用アダプターのオフライン契約テスト。"""

import tempfile
import warnings
from pathlib import Path
import unittest

warnings.filterwarnings(
    "ignore",
    message="agentmesh-platform is deprecated.*",
    category=DeprecationWarning,
)
from agentmesh.governance.policy import PolicyEngine  # noqa: E402

from agt_claude_demo import normalize_tool_call
from claude_demo import referenced_filename
from claude_file_tools import WRITE_TOOL
from common import seed_workspace, verify_workspace_result


AGENT_DID = "did:example:file-demo-agent"
POLICY_PATH = Path(__file__).parent / "policy" / "file_policy.yaml"


class GovernanceIntegrationTest(unittest.TestCase):
    """APIを呼ばず、共通ポリシーとアダプターの主要な契約を検証する。"""

    @classmethod
    def setUpClass(cls) -> None:
        """全テストで共有するPolicy Engineを一度だけ構築する。"""
        cls.engine = PolicyEngine(conflict_strategy="deny_overrides")
        cls.engine.load_yaml_file(str(POLICY_PATH))

    def decision(self, operation: str, filename: str) -> str:
        """指定したTool操作を評価し、AGTのAction文字列だけを返す。"""
        result = self.engine.evaluate(
            agent_did=AGENT_DID,
            stage="pre_tool",
            context={
                "action": {"type": operation},
                "resource": {"name": filename},
            },
        )
        return result.action

    def test_shared_policy_contract(self) -> None:
        """OpenAI版とClaude版が前提とする共通Policyを検証する。"""
        self.assertEqual(self.decision("read_file", "normal.txt"), "allow")
        self.assertEqual(self.decision("write_file", "normal.txt"), "allow")
        self.assertEqual(
            self.decision("write_file", "important.txt"),
            "require_approval",
        )
        self.assertEqual(self.decision("delete_file", "normal.txt"), "allow")
        self.assertEqual(self.decision("delete_file", "important.txt"), "deny")

    def test_claude_adapter_preserves_resource_name(self) -> None:
        """Claude側のアダプターがポリシー評価前にfilenameを書き換えないことを検証する。"""
        input_data = {"filename": "../normal.txt", "content": "unexpected"}

        operation, filename = normalize_tool_call(WRITE_TOOL, input_data)

        self.assertEqual(operation, "write_file")
        self.assertEqual(filename, "../normal.txt")
        self.assertEqual(referenced_filename(WRITE_TOOL, input_data), "../normal.txt")
        self.assertEqual(self.decision(operation, filename), "deny")

    def test_workspace_result_matches_rejected_write(self) -> None:
        """重要ファイルへの書き込み拒否後は初期内容が保持されることを検証する。"""
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            seed_workspace(workspace)
            (workspace / "normal.txt").unlink()

            verify_workspace_result(workspace, important_write_approved=False)

    def test_workspace_result_matches_approved_write(self) -> None:
        """重要ファイルへの書き込み承認後は指定内容へ更新されることを検証する。"""
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            seed_workspace(workspace)
            (workspace / "normal.txt").unlink()
            (workspace / "important.txt").write_text(
                "important: attempted update",
                encoding="utf-8",
            )

            verify_workspace_result(workspace, important_write_approved=True)


if __name__ == "__main__":
    unittest.main()
