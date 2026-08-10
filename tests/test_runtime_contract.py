from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import catalog  # noqa: E402


class RuntimeSourceContractTests(unittest.TestCase):
    def test_static_contract_matches_runtime_catalog(self):
        contract = json.loads(
            (ROOT / "runtime-contract.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(contract),
            {
                "schema_version",
                "agency_name",
                "catalog_schema_version",
                "content_digest_schema",
                "agency_manifest",
                "skills_manifest",
                "profile_root",
                "profile_path_template",
            },
        )
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(contract["agency_manifest"], "agency.json")
        self.assertEqual(contract["skills_manifest"], "skills-map.json")
        self.assertEqual(contract["profile_root"], "profiles")

        runtime = catalog.build_catalog()
        self.assertEqual(contract["agency_name"], runtime["agency"]["name"])
        self.assertEqual(
            contract["catalog_schema_version"], runtime["schema_version"]
        )
        self.assertEqual(
            contract["content_digest_schema"], runtime["content_digest_schema"]
        )
        self.assertEqual(
            contract["profile_path_template"],
            runtime["distribution"]["profile_path_template"],
        )

        agency = json.loads((ROOT / contract["agency_manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(agency["name"], contract["agency_name"])
        self.assertEqual(
            agency["distribution"]["profile_root"], contract["profile_root"]
        )
        self.assertEqual(
            agency["distribution"]["profile_path_template"],
            contract["profile_path_template"],
        )
        self.assertTrue((ROOT / contract["skills_manifest"]).is_file())


if __name__ == "__main__":
    unittest.main()
