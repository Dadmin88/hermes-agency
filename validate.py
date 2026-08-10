#!/usr/bin/env python3
"""Validate the static integrity of a Hermes Agency checkout."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROFILE_RE = re.compile(r"^agency-[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
EVAL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REVISION_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_DISTRIBUTION_FIELDS = ("name", "version", "description", "author", "license")
SOURCE_FIELDS = ("Canonical source", "Reviewed revision", "Review date", "Upstream author", "License")
ROUTING_ACTIONS = {
    "resolve-profile-presence",
    "route-same-profile-to-ready-node",
    "place-same-profile-then-route",
    "reselect-node-without-changing-profile",
    "decompose-and-resolve-profile-presence",
    "report-missing-specialization",
}


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing required file: {path}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON in {path}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"expected JSON object in {path}")
        return {}
    return value


def scalar_fields(path: Path, errors: list[str]) -> dict[str, str]:
    """Read the simple top-level scalar YAML used by distribution.yaml."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        errors.append(f"missing required file: {path}")
        return {}

    result: dict[str, str] = {}
    for line in lines:
        if not line or line[0].isspace() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def frontmatter_name(path: Path, errors: list[str]) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        errors.append(f"missing required file: {path}")
        return None

    if not lines or lines[0].strip() != "---":
        errors.append(f"missing YAML frontmatter in {path}")
        return None

    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        errors.append(f"unterminated YAML frontmatter in {path}")
        return None

    for line in lines[1:end]:
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            return value

    errors.append(f"frontmatter is missing name in {path}")
    return None


def source_fields(path: Path, errors: list[str]) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}

    values: dict[str, str] = {}
    for field in SOURCE_FIELDS:
        match = re.search(rf"(?mi)^\s*-?\s*{re.escape(field)}:\s*`?([^`\n]+?)`?\s*$", text)
        if not match:
            errors.append(f"SOURCE.md is missing '{field}' in {path}")
            continue
        values[field] = match.group(1).strip()

    revision = values.get("Reviewed revision")
    if revision and not REVISION_RE.fullmatch(revision):
        errors.append(f"invalid reviewed revision in {path}: {revision}")

    review_date = values.get("Review date")
    if review_date and not DATE_RE.fullmatch(review_date):
        errors.append(f"invalid review date in {path}: {review_date}")

    return values


def normalize_bundled(value: object, profile: str, errors: list[str]) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    errors.append(f"invalid bundled skill list for {profile}")
    return []


def validate_routing_evals(root: Path, roster_set: set[str], errors: list[str]) -> int:
    eval_path = root / "evals" / "routing.json"
    data = load_json(eval_path, errors)
    if not data:
        return 0

    if data.get("schema_version") != 1:
        errors.append(
            f"unsupported routing eval schema_version={data.get('schema_version')!r} in {eval_path}"
        )

    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        errors.append(f"routing evals must contain a non-empty cases list: {eval_path}")
        return 0

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        label = f"routing eval case #{index + 1}"
        if not isinstance(case, dict):
            errors.append(f"{label} is not an object")
            continue

        case_id = case.get("id")
        if not isinstance(case_id, str) or not EVAL_ID_RE.fullmatch(case_id):
            errors.append(f"{label} has invalid id: {case_id!r}")
        elif case_id in seen_ids:
            errors.append(f"duplicate routing eval id: {case_id}")
        else:
            seen_ids.add(case_id)

        task = case.get("task")
        if not isinstance(task, str) or not task.strip():
            errors.append(f"{label} has an empty task")

        expected_profile = case.get("expected_profile")
        if expected_profile is not None:
            if not isinstance(expected_profile, str) or expected_profile not in roster_set:
                errors.append(
                    f"{label} references unknown expected_profile: {expected_profile!r}"
                )

        action = case.get("expected_runtime_action")
        if action not in ROUTING_ACTIONS:
            errors.append(f"{label} has invalid expected_runtime_action: {action!r}")
            continue

        if action == "report-missing-specialization":
            if expected_profile is not None:
                errors.append(
                    f"{label} reports missing specialization but expected_profile is not null"
                )
        elif expected_profile is None:
            errors.append(
                f"{label} expects runtime action {action!r} but has no expected_profile"
            )

    return len(cases)


def validate(root: Path) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    agency = load_json(root / "agency.json", errors)
    skill_map = load_json(root / "skills-map.json", errors)
    profiles_root = root / "profiles"

    roster = agency.get("profiles", [])
    if not isinstance(roster, list):
        errors.append("agency.json profiles must be a list")
        roster = []

    roster_names: list[str] = []
    roster_categories: list[str] = []
    for index, item in enumerate(roster):
        if not isinstance(item, dict):
            errors.append(f"agency.json profile #{index + 1} is not an object")
            continue
        name = item.get("name")
        category = item.get("category")
        display_name = item.get("display_name")
        if not isinstance(name, str) or not PROFILE_RE.fullmatch(name):
            errors.append(f"invalid profile name in agency.json: {name!r}")
            continue
        if not isinstance(display_name, str) or not display_name.strip():
            errors.append(f"missing display_name for {name}")
        if not isinstance(category, str) or not category:
            errors.append(f"missing category for {name}")
            category = ""
        roster_names.append(name)
        roster_categories.append(category)

    if len(roster_names) != len(set(roster_names)):
        errors.append("agency.json contains duplicate profile names")

    declared_profile_count = agency.get("profile_count")
    if declared_profile_count != len(roster_names):
        errors.append(
            f"agency.json profile_count={declared_profile_count!r}, actual roster={len(roster_names)}"
        )

    declared_categories = agency.get("categories", {})
    actual_categories = dict(Counter(roster_categories))
    if declared_categories != actual_categories:
        errors.append(
            f"agency.json categories do not match roster: declared={declared_categories!r}, actual={actual_categories!r}"
        )

    filesystem_profiles = {
        path.name for path in profiles_root.iterdir() if path.is_dir()
    } if profiles_root.is_dir() else set()
    roster_set = set(roster_names)
    if filesystem_profiles != roster_set:
        missing = sorted(roster_set - filesystem_profiles)
        extra = sorted(filesystem_profiles - roster_set)
        if missing:
            errors.append(f"profile directories missing from filesystem: {', '.join(missing)}")
        if extra:
            errors.append(f"profile directories missing from agency.json: {', '.join(extra)}")

    map_profiles = skill_map.get("profiles", [])
    if not isinstance(map_profiles, list):
        errors.append("skills-map.json profiles must be a list")
        map_profiles = []

    map_by_name: dict[str, dict] = {}
    for item in map_profiles:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            errors.append("skills-map.json contains a profile without a valid name")
            continue
        name = item["name"]
        if name in map_by_name:
            errors.append(f"skills-map.json contains duplicate profile: {name}")
        map_by_name[name] = item

    if set(map_by_name) != roster_set:
        missing = sorted(roster_set - set(map_by_name))
        extra = sorted(set(map_by_name) - roster_set)
        if missing:
            errors.append(f"profiles missing from skills-map.json: {', '.join(missing)}")
        if extra:
            errors.append(f"unknown profiles in skills-map.json: {', '.join(extra)}")

    if skill_map.get("profile_count") != len(roster_names):
        errors.append(
            f"skills-map.json profile_count={skill_map.get('profile_count')!r}, actual roster={len(roster_names)}"
        )

    actual_skill_count = 0
    sourced_skill_count = 0
    target_remaining = 0

    for name in roster_names:
        profile_dir = profiles_root / name
        distribution = scalar_fields(profile_dir / "distribution.yaml", errors)
        for field in REQUIRED_DISTRIBUTION_FIELDS:
            if not distribution.get(field):
                errors.append(f"{name} distribution.yaml is missing {field}")
        if distribution.get("name") and distribution["name"] != name:
            errors.append(
                f"{name} distribution identity mismatch: {distribution['name']!r}"
            )

        soul_path = profile_dir / "SOUL.md"
        try:
            soul_text = soul_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            errors.append(f"missing required file: {soul_path}")
            soul_text = ""
        if soul_path.exists() and not soul_text:
            errors.append(f"empty SOUL.md: {soul_path}")

        skills_dir = profile_dir / "skills"
        actual_skills: list[str] = []
        if not skills_dir.is_dir():
            errors.append(f"missing skills directory: {skills_dir}")
        else:
            for skill_dir in sorted(path for path in skills_dir.iterdir() if path.is_dir()):
                skill_name = skill_dir.name
                if not SKILL_RE.fullmatch(skill_name):
                    errors.append(f"invalid skill directory name: {skill_dir}")
                skill_file = skill_dir / "SKILL.md"
                if not skill_file.is_file():
                    errors.append(f"missing SKILL.md: {skill_dir}")
                    continue
                declared_name = frontmatter_name(skill_file, errors)
                if declared_name and declared_name != skill_name:
                    errors.append(
                        f"skill identity mismatch in {skill_file}: frontmatter={declared_name!r}, directory={skill_name!r}"
                    )
                source_file = skill_dir / "SOURCE.md"
                if source_file.exists():
                    sourced_skill_count += 1
                    source_fields(source_file, errors)
                actual_skills.append(skill_name)

        if not actual_skills:
            errors.append(f"profile has no bundled skills: {name}")

        actual_skill_count += len(actual_skills)
        map_entry = map_by_name.get(name, {})
        map_category = map_entry.get("category")
        roster_entry = next((item for item in roster if isinstance(item, dict) and item.get("name") == name), {})
        if map_category != roster_entry.get("category"):
            errors.append(
                f"category mismatch for {name}: agency.json={roster_entry.get('category')!r}, skills-map.json={map_category!r}"
            )

        bundled = normalize_bundled(map_entry.get("bundled"), name, errors)
        if len(bundled) != len(set(bundled)):
            errors.append(f"duplicate bundled skill names in skills-map.json for {name}")
        if set(bundled) != set(actual_skills):
            missing = sorted(set(actual_skills) - set(bundled))
            stale = sorted(set(bundled) - set(actual_skills))
            errors.append(
                f"skill-map/filesystem mismatch for {name}: missing_from_map={missing}, missing_from_filesystem={stale}"
            )

        targets = map_entry.get("targets", [])
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            errors.append(f"invalid targets list for {name}")
        else:
            target_remaining += len(targets)

    declared_current = skill_map.get("current_bundled_skill_count")
    if declared_current != actual_skill_count:
        errors.append(
            f"skills-map.json current_bundled_skill_count={declared_current!r}, actual={actual_skill_count}"
        )

    declared_remaining = skill_map.get("remaining_target_skill_count")
    if declared_remaining != target_remaining:
        errors.append(
            f"skills-map.json remaining_target_skill_count={declared_remaining!r}, actual targets={target_remaining}"
        )

    target_skill_count = skill_map.get("target_skill_count")
    baseline_count = skill_map.get("baseline_bundled_skill_count")
    enrichment_count = skill_map.get("enrichment_skill_count", 0)
    schema_version = skill_map.get("schema_version", 1)

    if schema_version >= 2:
        if not all(isinstance(value, int) and value >= 0 for value in (target_skill_count, baseline_count, enrichment_count)):
            errors.append("schema v2 skill counts must be non-negative integers")
        else:
            if baseline_count + target_remaining != target_skill_count:
                errors.append(
                    "baseline skill math mismatch: "
                    f"baseline={baseline_count} + remaining={target_remaining} != target={target_skill_count}"
                )
            if baseline_count + enrichment_count != actual_skill_count:
                errors.append(
                    "total skill math mismatch: "
                    f"baseline={baseline_count} + enrichment={enrichment_count} != actual={actual_skill_count}"
                )
            if skill_map.get("baseline_complete") is True and (
                target_remaining != 0 or baseline_count != target_skill_count
            ):
                errors.append("baseline_complete is true but baseline targets are not complete")
    elif isinstance(target_skill_count, int):
        if actual_skill_count + target_remaining != target_skill_count:
            errors.append(
                f"schema v1 skill math mismatch: actual={actual_skill_count} + remaining={target_remaining} != target={target_skill_count}"
            )

    distribution_meta = agency.get("distribution", {})
    expected_distribution = {
        "format": "hermes-profile-distribution",
        "profile_identity_field": "name",
        "profile_root": "profiles",
        "profile_path_template": "profiles/{name}",
    }
    if distribution_meta != expected_distribution:
        errors.append(
            f"agency.json distribution contract mismatch: {distribution_meta!r}"
        )

    if agency.get("schema_version") != 2:
        errors.append(
            f"agency.json schema_version must be 2 for Fleet routing contract, got {agency.get('schema_version')!r}"
        )

    routing_meta = agency.get("routing", {})
    expected_routing = {
        "capability_manifest": "skills-map.json",
        "profile_metadata_template": "profiles/{name}/distribution.yaml",
        "selection_order": ["professional-profile", "eligible-node"],
        "live_presence_owner": "hermes-fleet",
        "missing_presence_behavior": "fleet-locate-or-place",
    }
    if routing_meta != expected_routing:
        errors.append(f"agency.json routing contract mismatch: {routing_meta!r}")
    else:
        capability_manifest = root / routing_meta["capability_manifest"]
        if not capability_manifest.is_file():
            errors.append(
                f"agency.json routing capability manifest does not exist: {capability_manifest}"
            )
        metadata_template = routing_meta["profile_metadata_template"]
        for name in roster_names:
            metadata_path = root / metadata_template.format(name=name)
            if not metadata_path.is_file():
                errors.append(
                    f"routing profile metadata path does not exist for {name}: {metadata_path}"
                )

    routing_eval_count = validate_routing_evals(root, roster_set, errors)

    stats = {
        "profiles": len(roster_names),
        "skills": actual_skill_count,
        "sourced_skills": sourced_skill_count,
        "remaining_targets": target_remaining,
        "routing_evals": routing_eval_count,
    }
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="repository root (default: directory containing validate.py)",
    )
    args = parser.parse_args()

    errors, stats = validate(args.root.resolve())
    if errors:
        print(f"FAIL: {len(errors)} validation error(s)", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "OK: "
        f"{stats['profiles']} profiles, "
        f"{stats['skills']} bundled skills, "
        f"{stats['sourced_skills']} sourced skills, "
        f"{stats['routing_evals']} routing evals, "
        f"{stats['remaining_targets']} remaining baseline targets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
