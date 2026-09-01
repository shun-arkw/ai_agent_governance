"""AGT 4.1.0からOPAとCedarを利用する外部ポリシー連携デモ。

Open Policy Agent 1.19.1のRegoポリシーと、cedarpy 4.8.7が内包するCedar
Policy Engineを、AGTの ``PolicyEngine`` へそれぞれ登録する。同じ5つの
ファイル操作を評価し、外部エンジンの判定がAGTの ``PolicyDecision`` へ
変換されることをAPI呼び出しなしで確認する。

AGT Native Policyは ``require_approval`` を表現できるが、AGT 4.1.0の標準的な
OPA／Cedar連携は外部エンジンの結果を ``allow`` または ``deny`` へ変換する。
そのため、このデモではimportant.txtへの書き込みは両エンジンともdenyになる。
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

warnings.filterwarnings(
    "ignore",
    message="agentmesh-platform is deprecated.*",
    category=DeprecationWarning,
)
from agentmesh.governance.policy import PolicyDecision, PolicyEngine  # noqa: E402


AGENT_DID = "did:example:file-demo-agent"
OPA_VERSION = "1.19.1"
CEDARPY_VERSION = "4.8.7"
CEDAR_ENGINE_VERSION = "4.8.2"
POLICY_DIR = Path(__file__).parent / "policy"
REGO_PATH = POLICY_DIR / "file_policy.rego"
CEDAR_PATH = POLICY_DIR / "file_policy.cedar"

BackendName = Literal["opa", "cedar"]
OPERATIONS = (
    ("read_file", "normal.txt"),
    ("write_file", "normal.txt"),
    ("write_file", "important.txt"),
    ("delete_file", "normal.txt"),
    ("delete_file", "important.txt"),
)


@dataclass(frozen=True)
class ExternalPolicyBackend:
    """AGTへ登録した外部ポリシーエンジンと、その表示情報。"""

    name: BackendName
    version: str
    policy_path: Path
    engine: PolicyEngine

    def evaluate(self, operation: str, filename: str) -> PolicyDecision:
        """ツール操作を外部エンジン向けのコンテキストへ変換して評価する。"""
        resource: dict[str, str] | str
        if self.name == "cedar":
            # Cedarではリソースを型付きEntity UIDとして表現する。
            resource = f"File::{json.dumps(filename)}"
        else:
            resource = {"name": filename}

        decision = self.engine.evaluate(
            agent_did=AGENT_DID,
            stage="pre_tool",
            context={
                "action": {"type": operation},
                "resource": resource,
            },
        )
        expected_reason = "OPA/Rego policy" if self.name == "opa" else "Cedar policy"
        if expected_reason not in decision.reason:
            raise RuntimeError(
                f"{self.name} evaluation did not complete: {decision.reason}"
            )
        return decision


def opa_binary() -> Path:
    """仮想環境内の固定版を優先し、利用するOPA CLIのパスを返す。"""
    configured = os.getenv("OPA_BINARY")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(sys.executable).with_name("opa"))
    system_binary = shutil.which("opa")
    if system_binary:
        candidates.append(Path(system_binary))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise RuntimeError("OPA CLI is required; expected version 1.19.1")


def installed_opa_version(binary: Path) -> str:
    """指定したOPA CLIのバージョンを返す。"""
    result = subprocess.run(
        [str(binary), "version"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Version:"):
            return line.partition(":")[2].strip()
    if not result.stdout:
        raise RuntimeError("OPA CLI is required; expected version 1.19.1")
    raise RuntimeError(f"Could not parse OPA version output: {result.stdout!r}")


def require_version(component: str, actual: str, expected: str) -> None:
    """比較条件を固定するため、実行時のバージョンが期待値と一致することを確認する。"""
    if actual != expected:
        raise RuntimeError(f"{component} {expected} is required; found {actual}")


def build_opa_backend() -> ExternalPolicyBackend:
    """RegoポリシーをOPA 1.19.1経由で評価するAGT Engineを構築する。"""
    binary = opa_binary()
    version = installed_opa_version(binary)
    require_version("OPA", version, OPA_VERSION)
    # AGT 4.1.0のOPAアダプターはPATH上の ``opa`` を呼ぶため、検証済みの
    # バイナリがあるディレクトリを、このプロセス内でのみPATHの先頭へ追加する。
    os.environ["PATH"] = f"{binary.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    engine = PolicyEngine(conflict_strategy="deny_overrides")
    engine.load_rego(rego_path=str(REGO_PATH), package="file_governance")
    return ExternalPolicyBackend("opa", version, REGO_PATH, engine)


def build_cedar_backend() -> ExternalPolicyBackend:
    """Cedarポリシーをcedarpy 4.8.7経由で評価するAGT Engineを構築する。"""
    try:
        version = importlib.metadata.version("cedarpy")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError("cedarpy 4.8.7 is required") from error
    require_version("cedarpy", version, CEDARPY_VERSION)
    engine = PolicyEngine(conflict_strategy="deny_overrides")
    engine.load_cedar(cedar_path=str(CEDAR_PATH), mode="cedarpy")
    return ExternalPolicyBackend("cedar", version, CEDAR_PATH, engine)


def run(backend_name: BackendName) -> None:
    """指定した外部エンジンで5つの共通操作を評価し、結果を表示する。"""
    backend = build_opa_backend() if backend_name == "opa" else build_cedar_backend()
    external = (
        f"OPA {backend.version}"
        if backend.name == "opa"
        else f"cedarpy {backend.version} cedar-engine={CEDAR_ENGINE_VERSION}"
    )
    print(
        f"governance=AGT 4.1.0 external={external} "
        f"policy={backend.policy_path.name}"
    )
    for operation, filename in OPERATIONS:
        decision = backend.evaluate(operation, filename)
        print(f"  {decision.action.upper():<5} {operation:<11} {filename}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "backend",
        choices=("opa", "cedar", "all"),
        nargs="?",
        default="all",
    )
    args = parser.parse_args()
    backend_names: tuple[BackendName, ...] = (
        ("opa", "cedar") if args.backend == "all" else (args.backend,)
    )
    for index, backend_name in enumerate(backend_names):
        if index:
            print()
        run(backend_name)


if __name__ == "__main__":
    main()
