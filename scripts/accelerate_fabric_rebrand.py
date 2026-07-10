#!/usr/bin/env python3
"""Patch the one-time Fabric rebrand migration for fast, legally safe moves."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = Path(__file__).with_name("apply_fabric_namespace_rebrand.py")
text = path.read_text()
text = text.replace(
    'subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)',
    'subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)',
)
text = text.replace(
    '    ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt",',
    '    ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt",\n    ".hcl", ".mod", ".webmanifest", ".jsonc",',
)
text = text.replace(
    '    "Dockerfile", "LICENSE", "NOTICE", "Makefile", "Procfile", "AGENTS.md",',
    '    "Dockerfile", "LICENSE", "NOTICE", "Makefile", "Procfile", "AGENTS.md",\n    ".gitignore", ".dockerignore",',
)
text = text.replace(
    'return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_BASENAMES or ".env" in path.name',
    'return (\n        path.suffix.lower() in TEXT_SUFFIXES\n        or path.name in TEXT_BASENAMES\n        or path.name.startswith("Dockerfile")\n        or not path.suffix\n        or ".env" in path.name\n    )',
)
text = text.replace(
    '        run("git", "mv", str(relative), str(target_relative))',
    '        source.rename(target)',
)
text = text.replace(
    '            run("git", "rm", str(target.relative_to(ROOT)))',
    '            target.unlink()',
)
text = text.replace(
    '        if re.search("paperclip", relative, re.I):\n            path_hits.append(relative)',
    '        if path.exists() and re.search("paperclip", relative, re.I):\n            path_hits.append(relative)',
)
text = text.replace(
    '    if not path.exists() or not path.is_file() or not is_text(path):\n        return',
    '    if not path.exists() or not path.is_file() or not is_text(path):\n        return\n    if path.name in {"LICENSE", "NOTICE"}:\n        return',
)
text = text.replace(
    '        if path.exists() and path.is_file() and is_text(path):',
    '        if path.exists() and path.is_file() and is_text(path) and path.name not in {"LICENSE", "NOTICE"}:',
)
text = text.replace(
    '        updated = polish_code_strings(replace_technical(original))',
    '        updated = replace_technical(original)\n        updated = updated.replace(\'"HermesFabric"\', \'"Hermes Fabric"\')\n        updated = updated.replace("\'HermesFabric\'", "\'Hermes Fabric\'")\n        updated = updated.replace("`HermesFabric`", "`Hermes Fabric`")\n        updated = updated.replace(">HermesFabric<", ">Hermes Fabric<")',
)
text = text.replace(
    '\ndef rewrite_brand_guard() -> None:\n',
    '''\ndef prune_empty_directories() -> None:\n    directories = [\n        candidate\n        for candidate in ROOT.rglob("*")\n        if candidate.is_dir() and ".git" not in candidate.relative_to(ROOT).parts\n    ]\n    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):\n        try:\n            directory.rmdir()\n        except OSError:\n            pass\n\n\ndef rewrite_brand_guard() -> None:\n''',
)
text = text.replace(
    '    rename_tracked_paths()\n    # Re-run content migration',
    '    rename_tracked_paths()\n    prune_empty_directories()\n    # Re-run content migration',
)
path.write_text(text)

normalizer = ROOT / "apps/fabric/scripts/normalize-upstream-import.py"
text = normalizer.read_text()
text = text.replace(
    '    ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt",',
    '    ".rs", ".sh", ".sql", ".svg", ".toml", ".ts", ".tsx", ".txt",\n    ".hcl", ".mod", ".webmanifest", ".jsonc",',
)
text = text.replace(
    'TEXT_BASENAMES = {"Dockerfile", "LICENSE", "NOTICE", "Makefile", "Procfile"}',
    'TEXT_BASENAMES = {"Dockerfile", "LICENSE", "NOTICE", "Makefile", "Procfile", ".gitignore", ".dockerignore"}',
)
text = text.replace(
    'return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_BASENAMES or ".env" in path.name',
    'return (\n        path.suffix.lower() in TEXT_SUFFIXES\n        or path.name in TEXT_BASENAMES\n        or path.name.startswith("Dockerfile")\n        or not path.suffix\n        or ".env" in path.name\n    )',
)
text = text.replace(
    '    for path in walk_files(root):\n        try:',
    '    for path in walk_files(root):\n        if path.name in {"LICENSE", "NOTICE"}:\n            continue\n        try:',
)
text = text.replace(
    '        if path.is_symlink() or not path.is_file() or not is_text(path):\n            continue',
    '        if path.is_symlink() or not path.is_file() or not is_text(path):\n            continue\n        if path.name in {"LICENSE", "NOTICE"}:\n            continue',
)
normalizer.write_text(text)

sync_workflow = ROOT / ".github/workflows/fabric-upstream-sync.yml"
text = sync_workflow.read_text()
text = text.replace(
    '              try:\n                  content = open(path, encoding="utf-8").read().lower()',
    '              if path.endswith("/LICENSE") or path.endswith("/NOTICE"):\n                  continue\n              try:\n                  content = open(path, encoding="utf-8").read().lower()',
)
sync_workflow.write_text(text)
