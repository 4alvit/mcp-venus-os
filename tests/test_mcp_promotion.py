"""Keep the repository's immutable RC promotion and owned version inputs aligned."""

import json
import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import version_plan  # noqa: E402
import version_receipt  # noqa: E402


class McpPromotionTests(unittest.TestCase):
    """Exercise the actual policy and manifests instead of a copied declaration."""

    def test_rc_contains_final_versions_and_preserves_candidate_origin(self) -> None:
        """RC wheel, runtime and lock versions can be published without a rebuild."""
        policy = json.loads((ROOT / ".release-policy.json").read_text())
        assert policy["versioning"]["promotion"] == "promote-bytes"
        base = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
        plan = version_plan.create_plan(base, "rc", 3, "a" * 40, policy, 9)
        assert plan["version"] == f"{base}-rc.3"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for item in policy["versioning"]["files"]:
                target = root / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / item["path"], target)
            evidence = version_plan.sync_versions(root, policy, plan)
            version_plan.sync_versions(root, policy, plan, check=True)
            version_receipt.verify_current_inputs(root, evidence)
            assert (
                tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"] == base
            )
            assert f'__version__ = "{base}"' in (root / "src/mcp_venus_os/__init__.py").read_text()
            packages = tomllib.loads((root / "uv.lock").read_text())["package"]
            assert next(p["version"] for p in packages if p["name"] == "mcp-venus-os") == base
            (root / "pyproject.toml").write_text('[project]\nversion="9.9.9"\n')
            with pytest.raises(ValueError, match="changed after version sync"):
                version_receipt.verify_current_inputs(root, evidence)
        for item in policy["versioning"]["artifacts"]:
            assert version_plan.projected_value(plan, item) == base

    def test_beta_keeps_its_prerelease_version(self) -> None:
        """Only an RC may carry final package versions for unchanged promotion."""
        policy = json.loads((ROOT / ".release-policy.json").read_text())
        plan = version_plan.create_plan("1.2.3", "beta", 2, "a" * 40, policy, 8)
        assert (
            version_plan.projected_value(plan, {"value": "package", "ecosystem": "pep440"})
            == "1.2.3b2"
        )
        assert version_plan.projected_value(plan, {"value": "package"}) == "1.2.3-beta.2"

    def test_old_final_build_plan_cannot_be_reinterpreted(self) -> None:
        """Changing policy invalidates old receipts instead of relabelling their bytes."""
        policy = json.loads((ROOT / ".release-policy.json").read_text())
        old = json.loads(json.dumps(policy))
        old["versioning"]["promotion"] = "final-build"
        plan = version_plan.create_plan("1.2.3", "rc", 2, "a" * 40, old, 8)
        with pytest.raises(ValueError, match="policy digest mismatch"):
            version_plan.validate_plan(plan, policy)


if __name__ == "__main__":
    unittest.main()
