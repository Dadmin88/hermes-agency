"""Deterministic materialization, validation, classification, and content hashing."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from .models import RiskClass, ValidationFinding, ValidationResult

POLICY_VERSION = "agency-skill-governance-v1"
VALIDATOR_VERSION = "agency-validator-v1"
SCANNER_VERSION = "agency-static-scanner-v1"
_ALLOWED_ACTIONS = {"create", "edit", "patch", "delete", "write_file", "remove_file"}
_ALLOWED_SUPPORT_ROOTS = {"references", "templates", "scripts", "assets"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_./+\-=]{12,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
)
_PII_PATTERNS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
)
_SECURITY_TERMS = re.compile(
    r"(?i)(\bsubprocess\b|\bos\.system\b|\bshell\b|\bcurl\b|\bwget\b|"
    r"\brequests\.|\bhttpx\.|\bpip install\b|\bnpm install\b|credentials?|/etc/|\.env\b)"
)
_GOVERNANCE_TERMS = re.compile(
    r"(?i)(skill[_ -]?governance|write_approval|external_dirs|approv(?:al|er)|audit|"
    r"promot(?:e|er|ion)|agency-ceo|agency-orchestrator|security-review)"
)
_PROMPT_INJECTION_TERMS = re.compile(
    r"(?i)(ignore (?:all |the )?(?:previous|system) instructions|reveal (?:the )?(?:system prompt|secrets?)|"
    r"disable (?:security|validation|approval)|bypass (?:policy|governance|scanner))"
)
_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z"}
_UNICODE_CONTROLS = {"Cf", "Cs"}


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> Any:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_skill_name(name: Any) -> str:
    value = str(name or "")
    if value != unicodedata.normalize("NFC", value) or not _NAME_RE.fullmatch(value):
        raise ValueError("skill name must be canonical lowercase ASCII and at most 64 characters")
    return value


def safe_relative_path(value: Any, *, allow_skill_md: bool = False) -> PurePosixPath:
    raw = str(value or "")
    if not raw or "\\" in raw or "%" in raw or any(ord(ch) < 32 for ch in raw):
        raise ValueError("path contains empty, encoded, backslash, or control-character ambiguity")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("path must be normalized and relative")
    if any(part.rstrip(". ") != part for part in path.parts):
        raise ValueError("path has trailing dot/space alias")
    if allow_skill_md and path.as_posix() == "SKILL.md":
        return path
    if not path.parts or path.parts[0] not in _ALLOWED_SUPPORT_ROOTS:
        raise ValueError("support file must be below references/templates/scripts/assets")
    return path


def _frontmatter(text: str, expected_name: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter is not terminated")
    loaded = yaml.load(text[4:end], Loader=UniqueKeyLoader)
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    if loaded.get("name") != expected_name:
        raise ValueError("frontmatter name must match canonical skill name")
    if not isinstance(loaded.get("description"), str) or not loaded["description"].strip():
        raise ValueError("frontmatter description is required")
    if len(loaded["description"]) > 500:
        raise ValueError("frontmatter description exceeds 500 characters")
    return loaded


def _copy_regular_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    root_info = source.lstat()
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise ValueError("source tree root must be a non-symlink directory")
    destination.mkdir(parents=True, exist_ok=True)
    for current, dirnames, filenames, directory_fd in os.fwalk(
        source, topdown=True, follow_symlinks=False
    ):
        current_path = Path(current)
        relative_dir = current_path.relative_to(source)
        target_dir = destination / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in list(dirnames):
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"unsupported directory entry: {(relative_dir / name).as_posix()}")
        for name in sorted(filenames):
            relative = relative_dir / name
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError(f"unsupported or linked file: {relative.as_posix()}")
            source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            target = destination / relative
            target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                while chunk := os.read(source_fd, 65536):
                    remaining = memoryview(chunk)
                    while remaining:
                        written = os.write(target_fd, remaining)
                        remaining = remaining[written:]
                os.fsync(target_fd)
                after = os.fstat(source_fd)
                stable_fields = (
                    "st_dev",
                    "st_ino",
                    "st_mode",
                    "st_nlink",
                    "st_size",
                    "st_mtime_ns",
                )
                if any(getattr(after, field) != getattr(before, field) for field in stable_fields):
                    raise RuntimeError(f"source changed while copying: {relative.as_posix()}")
            finally:
                os.close(source_fd)
                os.close(target_fd)


def materialize(
    payload: dict[str, Any], baseline: Path | None, destination: Path
) -> tuple[str, str]:
    action = str(payload.get("action") or "")
    if action not in _ALLOWED_ACTIONS:
        raise ValueError("unsupported action")
    name = validate_skill_name(payload.get("name"))
    destination.mkdir(parents=True, mode=0o700)
    if baseline is not None and baseline.exists():
        _copy_regular_tree(baseline, destination)

    if action == "delete":
        shutil.rmtree(destination)
        return action, name
    if action in {"create", "edit"}:
        content = payload.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{action} requires string content")
        if action == "create" and baseline is not None and baseline.exists():
            raise ValueError("create conflicts with an existing shared skill")
        (destination / "SKILL.md").write_text(content, encoding="utf-8")
    elif action == "patch":
        old = payload.get("old_string")
        new = payload.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old:
            raise ValueError("patch requires non-empty old_string and string new_string")
        skill_md = destination / "SKILL.md"
        current = skill_md.read_text(encoding="utf-8")
        count = current.count(old)
        if count != 1 and not (payload.get("replace_all") is True and count > 0):
            raise ValueError("patch preimage must match deterministically")
        skill_md.write_text(
            current.replace(old, new, -1 if payload.get("replace_all") else 1), encoding="utf-8"
        )
    elif action in {"write_file", "remove_file"}:
        relative = safe_relative_path(payload.get("file_path"), allow_skill_md=False)
        target = destination.joinpath(*relative.parts)
        if action == "write_file":
            content = payload.get("file_content")
            if not isinstance(content, str):
                raise ValueError("write_file requires string file_content")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        else:
            if not target.is_file() or target.is_symlink():
                raise ValueError("remove_file target is not a regular file")
            target.unlink()
    return action, name


def tree_manifest(root: Path, *, generation: bool = False) -> tuple[list[dict[str, Any]], str]:
    manifest: list[dict[str, Any]] = []
    total = 0
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink() or not (path.is_dir() or stat.S_ISREG(info.st_mode)):
            raise ValueError(f"unsupported filesystem entry: {path.relative_to(root)}")
        if path.is_dir():
            continue
        if info.st_nlink != 1:
            raise ValueError(f"hard-linked file is not allowed: {path.relative_to(root)}")
        relative = path.relative_to(root).as_posix()
        if generation:
            parts = PurePosixPath(relative).parts
            if len(parts) < 2:
                raise ValueError("generation files must be nested below a canonical skill name")
            validate_skill_name(parts[0])
            safe_relative_path(PurePosixPath(*parts[1:]).as_posix(), allow_skill_md=True)
        else:
            safe_relative_path(relative, allow_skill_md=True)
        data = path.read_bytes()
        total += len(data)
        if len(manifest) >= 128 or total > 2 * 1024 * 1024:
            raise ValueError("candidate exceeds file-count or byte limit")
        manifest.append({"path": relative, "size": len(data), "sha256": sha256_bytes(data)})
    return manifest, sha256_bytes(canonical_json(manifest))


def validate_candidate(root: Path, skill_name: str, action: str) -> ValidationResult:
    findings: list[ValidationFinding] = []
    security = action in {"delete", "write_file", "remove_file"}
    governance = action == "delete"
    quarantine = False
    digest: str | None = None
    if action == "delete":
        return ValidationResult(
            True, False, RiskClass.GOVERNANCE, sha256_bytes(b"deleted"), None, ()
        )
    try:
        manifest, digest = tree_manifest(root)
        if not manifest or not (root / "SKILL.md").is_file():
            raise ValueError("candidate must contain SKILL.md")
        text = (root / "SKILL.md").read_text(encoding="utf-8")
        _frontmatter(text, skill_name)
        for item in manifest:
            path = root / item["path"]
            data = path.read_bytes()
            scan_text = data.decode("utf-8")
            if any(unicodedata.category(ch) in _UNICODE_CONTROLS for ch in scan_text):
                findings.append(
                    ValidationFinding(
                        "UNICODE_CONTROL",
                        "error",
                        item["path"],
                        "hidden Unicode controls are forbidden",
                    )
                )
                quarantine = True
            if path.suffix.lower() in _ARCHIVE_SUFFIXES:
                findings.append(
                    ValidationFinding(
                        "ARCHIVE_FORBIDDEN",
                        "error",
                        item["path"],
                        "nested archives are not accepted",
                    )
                )
                quarantine = True
            if _PROMPT_INJECTION_TERMS.search(scan_text):
                findings.append(
                    ValidationFinding(
                        "PROMPT_INJECTION",
                        "error",
                        item["path"],
                        "instruction-confusion pattern detected",
                    )
                )
                quarantine = True
            decoded_candidates = [scan_text]
            for token in re.findall(r"[A-Za-z0-9+/]{24,}={0,2}", scan_text):
                try:
                    decoded_candidates.append(
                        base64.b64decode(token, validate=True).decode("utf-8")
                    )
                except (ValueError, UnicodeError):
                    pass
            for pattern in _SECRET_PATTERNS:
                if any(pattern.search(candidate) for candidate in decoded_candidates):
                    findings.append(
                        ValidationFinding(
                            "SECRET_DETECTED",
                            "error",
                            item["path"],
                            "high-confidence secret pattern detected",
                        )
                    )
                    quarantine = True
            for pattern in _PII_PATTERNS:
                if pattern.search(scan_text):
                    findings.append(
                        ValidationFinding(
                            "PII_DETECTED",
                            "error",
                            item["path"],
                            "PII-like value requires explicit purpose and security review",
                        )
                    )
                    quarantine = True
            security = (
                security
                or item["path"].startswith("scripts/")
                or bool(_SECURITY_TERMS.search(scan_text))
            )
            governance = governance or bool(_GOVERNANCE_TERMS.search(scan_text))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        findings.append(ValidationFinding("INVALID_CANDIDATE", "error", "", str(exc)))
    valid = not findings
    if governance and security:
        risk = RiskClass.SECURITY_GOVERNANCE
    elif governance:
        risk = RiskClass.GOVERNANCE
    elif security:
        risk = RiskClass.SECURITY
    else:
        risk = RiskClass.ROUTINE
    return ValidationResult(
        valid, quarantine, risk, digest, str(root) if valid else None, tuple(findings)
    )


def fsync_tree(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    for path in [*sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True), root]:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
