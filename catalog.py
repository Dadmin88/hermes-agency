#!/usr/bin/env python3
"""Emit the runtime-facing Hermes Agency profile catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
AGENCY_PATH = ROOT / "agency.json"
SKILLS_PATH = ROOT / "skills-map.json"


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError("distribution scalar must be a string")
        return parsed
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _distribution_description(path: Path) -> str:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line[0].isspace() or ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        if key == "description":
            description = _yaml_scalar(value)
            if not description.strip():
                raise ValueError(f"{path}: description is empty")
            return description
    raise ValueError(f"{path}: description is missing")


def build_catalog() -> dict:
    agency = _load_json(AGENCY_PATH)
    skills = _load_json(SKILLS_PATH)

    skill_profiles = skills.get("profiles")
    agency_profiles = agency.get("profiles")
    if not isinstance(skill_profiles, list) or not isinstance(agency_profiles, list):
        raise ValueError("agency.json and skills-map.json must contain profile arrays")

    skill_by_name = {
        item["name"]: item
        for item in skill_profiles
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    agency_names = [item.get("name") for item in agency_profiles if isinstance(item, dict)]
    if len(agency_names) != len(agency_profiles) or len(set(agency_names)) != len(agency_names):
        raise ValueError("agency.json contains invalid or duplicate profile names")
    if set(agency_names) != set(skill_by_name):
        raise ValueError("agency.json and skills-map.json profile sets differ")

    distribution = agency["distribution"]
    routing = agency["routing"]
    profile_root = ROOT / distribution["profile_root"]
    path_template = distribution["profile_path_template"]
    version = agency["version"]

    entries = []
    for profile in agency_profiles:
        name = profile["name"]
        skill_profile = skill_by_name[name]
        bundled = skill_profile.get("bundled")
        category = skill_profile.get("category")
        priority = skill_profile.get("priority")
        if not isinstance(bundled, list) or not all(isinstance(item, str) and item for item in bundled):
            raise ValueError(f"{name}: bundled capabilities are invalid")
        if not isinstance(category, str) or not category:
            raise ValueError(f"{name}: category is invalid")
        if priority not in {"standard", "backbone"}:
            raise ValueError(f"{name}: priority is invalid")

        relative_path = path_template.format(name=name)
        manifest_path = profile_root / name / "distribution.yaml"
        entries.append(
            {
                "name": name,
                "version": version,
                "category": category,
                "priority": priority,
                "description": _distribution_description(manifest_path),
                "distribution_path": relative_path,
                "capabilities": sorted(set(bundled)),
            }
        )

    entries.sort(key=lambda item: item["name"])
    return {
        "schema_version": 1,
        "agency": {
            "name": agency["name"],
            "version": version,
            "profile_count": agency["profile_count"],
            "orchestrator": agency["orchestrator"],
        },
        "distribution": {
            "format": distribution["format"],
            "profile_identity_field": distribution["profile_identity_field"],
            "profile_path_template": path_template,
        },
        "routing": {
            "selection_order": routing["selection_order"],
            "live_presence_owner": routing["live_presence_owner"],
            "missing_presence_behavior": routing["missing_presence_behavior"],
        },
        "profiles": entries,
    }


def _filter_catalog(catalog: dict, profile_name: str | None, category: str | None) -> dict:
    if profile_name and category:
        raise ValueError("choose either --profile or --category")
    profiles = catalog["profiles"]
    if profile_name:
        profiles = [profile for profile in profiles if profile["name"] == profile_name]
        if not profiles:
            raise ValueError(f"unknown profile: {profile_name}")
    elif category:
        profiles = [profile for profile in profiles if profile["category"] == category]
        if not profiles:
            raise ValueError(f"unknown or empty category: {category}")
    filtered = dict(catalog)
    filtered["profiles"] = profiles
    return filtered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Emit the Fleet-facing Hermes Agency runtime catalog.")
    parser.add_argument("--profile", help="emit one profile by stable profile name")
    parser.add_argument("--category", help="emit profiles in one category")
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    args = parser.parse_args(argv)

    try:
        catalog = _filter_catalog(build_catalog(), args.profile, args.category)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    if args.compact:
        print(json.dumps(catalog, separators=(",", ":"), sort_keys=True))
    else:
        print(json.dumps(catalog, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
