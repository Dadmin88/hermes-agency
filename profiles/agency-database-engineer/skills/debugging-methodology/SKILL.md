---
name: debugging-methodology
description: Systematic 4-phase debugging: reproduce, isolate, fix, verify
tags: [engineering, debugging, troubleshooting, logs, errors]
---

# Debugging Methodology

## When to Use
When encountering a bug, error, or unexpected behavior. Instead of trying random fixes, follow this systematic approach.

## Prerequisites
- Access to error messages, logs, or reproduction steps
- Terminal access for running commands

## Steps

### Phase 1: Reproduce
1. Get the exact error message — copy the full traceback/stack trace
2. Identify reproduction steps — what triggers the error?
3. Confirm it's reproducible — run it 2-3 times
4. Check: is it intermittent or consistent?

### Phase 2: Isolate
1. Read the error message carefully — it usually tells you what's wrong
2. Find the exact line/file mentioned in the traceback
3. Add logging or print statements around the failure point
4. Binary search: comment out half the code, see if error persists
5. Check recent changes: `git log --oneline -10` and `git diff HEAD~3`

### Phase 3: Fix
1. Understand the root cause before fixing
2. Make ONE change at a time
3. Test after each change
4. If the fix is complex, break it into smaller steps

### Phase 4: Verify
1. Run the original reproduction steps — error should be gone
2. Run existing tests — no regressions
3. Test edge cases — does the fix handle boundary conditions?
4. Check for similar bugs elsewhere in the codebase

## Tool Usage
- `terminal` for running commands, checking logs, git operations
- `read_file` for reading error source code
- `search_files` for finding similar patterns in the codebase

## Pitfalls
1. Don't fix symptoms — find the root cause
2. Don't make multiple changes at once — you won't know what fixed it
3. Don't skip verification — "it works on my machine" isn't enough
4. Don't ignore the error message — it's telling you exactly what's wrong
5. Don't assume the bug is where you think it is — check the full stack trace

## Quick Reference
```
1. REPRODUCE: Get exact error, confirm reproducibility
2. ISOLATE:   Read error, find source, binary search
3. FIX:       Understand root cause, one change at a time
4. VERIFY:    Repro steps pass, no regressions, edge cases
```

## Common Debugging Commands
```bash
# Recent changes
git log --oneline -10
git diff HEAD~3

# Find where error originates
grep -rn "error_message" --include="*.py"

# Check logs
tail -50 /var/log/app.log
journalctl --user -u service-name --since "5 min ago"

# Python debugging
python3 -c "import traceback; traceback.print_exc()"
python3 -m pdb script.py
```