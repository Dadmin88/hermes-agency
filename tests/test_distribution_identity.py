from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGENCY = json.loads((ROOT / "agency.json").read_text(encoding="utf-8"))


class DistributionIdentityTests(unittest.TestCase):
    def test_every_profile_distribution_matches_agency_release_identity(self):
        agency_version = AGENCY["version"]
        for profile in AGENCY["profiles"]:
            name = profile["name"]
            manifest_path = ROOT / profile["path"] / "distribution.yaml"
            with self.subTest(profile=name):
                manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                self.assertIsInstance(manifest, dict)
                self.assertEqual(manifest.get("name"), name)
                self.assertEqual(manifest.get("version"), agency_version)
                self.assertEqual(manifest.get("description"), profile["description"])

    def test_routing_contract_uses_stable_profile_identity(self):
        distribution = AGENCY["distribution"]
        routing = AGENCY["routing"]
        self.assertEqual(distribution["format"], "hermes-profile-distribution")
        self.assertEqual(distribution["profile_identity_field"], "name")
        self.assertEqual(distribution["profile_path_template"], "profiles/{name}")
        self.assertEqual(routing["selection_order"], ["professional-profile", "eligible-node"])
        self.assertEqual(routing["live_presence_owner"], "hermes-fleet")
        self.assertEqual(routing["missing_presence_behavior"], "fleet-locate-or-place")


if __name__ == "__main__":
    unittest.main()
