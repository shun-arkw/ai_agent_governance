"""AGTからOPA／Cedarを利用する外部ポリシー連携の契約テスト。"""

import importlib.metadata
import unittest

from external_policy_demo import (
    CEDARPY_VERSION,
    OPA_VERSION,
    OPERATIONS,
    build_cedar_backend,
    build_opa_backend,
    installed_opa_version,
    opa_binary,
)


EXPECTED_ACTIONS = ("allow", "allow", "deny", "allow", "deny")


def opa_1_19_1_available() -> bool:
    """OPA 1.19.1を実行できる場合にTrueを返す。"""
    try:
        return installed_opa_version(opa_binary()) == OPA_VERSION
    except (OSError, RuntimeError, ValueError):
        return False


def cedarpy_4_8_7_available() -> bool:
    """cedarpy 4.8.7を利用できる場合にTrueを返す。"""
    try:
        return importlib.metadata.version("cedarpy") == CEDARPY_VERSION
    except importlib.metadata.PackageNotFoundError:
        return False


class ExternalPolicyIntegrationTest(unittest.TestCase):
    """外部エンジンの判定がAGT PolicyDecisionへ正しく変換されることを検証する。"""

    def assert_policy_contract(self, backend) -> None:
        """5つの共通操作に対するallow／denyの並びを検証する。"""
        actions = tuple(
            backend.evaluate(operation, filename).action
            for operation, filename in OPERATIONS
        )
        self.assertEqual(actions, EXPECTED_ACTIONS)

    @unittest.skipUnless(opa_1_19_1_available(), "OPA 1.19.1 is not installed")
    def test_opa_policy_contract(self) -> None:
        """Regoの判定がAGT経由でallow／denyへ変換されることを検証する。"""
        self.assert_policy_contract(build_opa_backend())

    @unittest.skipUnless(cedarpy_4_8_7_available(), "cedarpy 4.8.7 is not installed")
    def test_cedar_policy_contract(self) -> None:
        """Cedarの判定がAGT経由でallow／denyへ変換されることを検証する。"""
        self.assert_policy_contract(build_cedar_backend())


if __name__ == "__main__":
    unittest.main()
