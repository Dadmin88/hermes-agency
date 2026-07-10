#!/usr/bin/env python3
"""Patch the one-time Fabric rebrand migration for fast filesystem-native moves."""
from pathlib import Path

path = Path(__file__).with_name("apply_fabric_namespace_rebrand.py")
text = path.read_text()
text = text.replace(
    'subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)',
    'subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT)',
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
path.write_text(text)
