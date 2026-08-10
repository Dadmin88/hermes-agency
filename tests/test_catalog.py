from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402


class RuntimeCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_and_runtime_focused(self):
        value = catalog.build_catalog()
        self.assertEqual(value["schema_version"], 1)
        self.assertEqual(value["agency"]["profile_count"], 83)
        self.assertEqual(len(value["profiles"]), 83)
        self.assertEqual(
            value["routing"]["selection_order"],
            ["professional-profile", "eligible-node"],
        )
        self.assertEqual(value["routing"]["live_presence_owner"], "hermes-fleet")
        self.assertEqual(value["routing"]["missing_presence_behavior"], "fleet-locate-or-place")

        names = [profile["name"] for profile in value["profiles"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))

        for profile in value["profiles"]:
            with self.subTest(profile=profile["name"]):
                self.assertEqual(profile["version"], value["agency"]["version"])
                self.assertTrue(profile["description"].strip())
                self.assertTrue(profile["capabilities"])
                self.assertEqual(profile["capabilities"], sorted(set(profile["capabilities"])))
                profile_dir = ROOT / profile["distribution_path"]
                self.assertTrue((profile_dir / "distribution.yaml").is_file())
                actual_skills = sorted(
                    path.parent.name for path in (profile_dir / "skills").glob("*/SKILL.md")
                )
                self.assertEqual(profile["capabilities"], actual_skills)

    def test_profile_filter_emits_one_stable_profile(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "catalog.py"), "--profile", "agency-backend-engineer", "--compact"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual([profile["name"] for profile in value["profiles"]], ["agency-backend-engineer"])
        self.assertIn("api-design", value["profiles"][0]["capabilities"])

    def test_category_filter_is_exact(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "catalog.py"), "--category", "qa", "--compact"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(len(value["profiles"]), 8)
        self.assertTrue(all(profile["category"] == "qa" for profile in value["profiles"]))

    def test_unknown_profile_fails_closed(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "catalog.py"), "--profile", "agency-does-not-exist"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown profile", result.stderr)


if __name__ == "__main__":
    unittest.main()
