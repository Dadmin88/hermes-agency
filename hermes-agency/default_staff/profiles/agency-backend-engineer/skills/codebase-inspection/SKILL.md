---
name: codebase-inspection
description: Navigate and understand unfamiliar codebases efficiently
tags: [engineering, codebase, navigation, grep, structure]
---

# Codebase Inspection

## When to Use
When you need to understand a new or unfamiliar codebase — find files, understand project structure, locate specific code patterns, or assess codebase size and complexity.

## Prerequisites
- Terminal access with grep/ripgrep, find, and wc available
- File read access

## Steps

### Step 1: Map the top-level structure
```bash
# See directory tree (2 levels deep)
find . -maxdepth 2 -type f | head -50

# Count files by extension
find . -type f | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20

# See directory sizes
du -sh */ | sort -rh | head -10
```

### Step 2: Find the entry point
```bash
# Common entry points
ls -la main.* app.* index.* server.* Makefile Dockerfile package.json pyproject.toml 2>/dev/null

# For Python projects
find . -name "__main__.py" -o -name "main.py" -o -name "app.py" | head -5

# For Node projects
cat package.json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('scripts',{}))"
```

### Step 3: Search for patterns
```bash
# Find function/class definitions
grep -rn "def \|class \|function \|const.*=.*=>" --include="*.py" --include="*.js" --include="*.ts" | head -20

# Find imports/dependencies
grep -rn "^import \|^from \|^require\|^import" --include="*.py" --include="*.js" | head -20

# Find configuration
find . -name "*.config.*" -o -name "*.env*" -o -name "settings.*" | head -10
```

### Step 4: Assess codebase metrics
```bash
# Lines of code by language (if pygount available)
pygount --format=summary . 2>/dev/null || find . -name "*.py" -exec wc -l {} + | tail -1

# Count test files
find . -name "test_*" -o -name "*_test.*" -o -name "*.spec.*" | wc -l
```

### Step 5: Read key files
Read the following in order:
1. README.md — project overview
2. AGENTS.md or CONTRIBUTING.md — contributor guidelines
3. Main entry point — how the app starts
4. Config files — environment and settings
5. Test files — expected behavior

## Tool Usage
- `terminal` for grep, find, wc, du commands
- `read_file` for reading specific files
- `search_files` for content and file searches

## Pitfalls
1. Don't read every file — use grep to narrow down first
2. Don't assume entry points — check multiple conventions
3. Don't ignore test files — they document expected behavior
4. Don't skip README/AGENTS.md — they contain project-specific rules

## Verification
- Can you describe the project structure in 3 sentences?
- Can you identify the main entry point?
- Can you list the top 3 dependencies?
- Can you find where a specific feature is implemented?

## Quick Reference
```
Structure: find . -maxdepth 2 -type f | head -50
Patterns:  grep -rn "pattern" --include="*.py"
Metrics:   find . -name "*.py" -exec wc -l {} + | tail -1
Entry:     ls main.* app.* index.* server.* 2>/dev/null
```