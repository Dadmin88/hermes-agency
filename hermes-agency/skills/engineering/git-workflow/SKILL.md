---
name: git-workflow
description: Git branching, committing, PRs, and conflict resolution
tags: [engineering, git, branching, commits, pr, merge]
---

# Git Workflow

## When to Use
When creating branches, writing commits, opening PRs, resolving conflicts, or managing releases.

## Prerequisites
- Git installed and configured
- Repository access

## Steps

### Step 1: Create a feature branch
```bash
# Update main
git checkout main && git pull origin main

# Create feature branch
git checkout -b feature/description
# or
git checkout -b fix/issue-number-description
```

### Step 2: Make focused commits
```bash
# Stage specific files
git add path/to/file

# Write clear commit messages
git commit -m "type: short description

- What changed and why
- Any breaking changes
- References to issues"
```

Commit types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

### Step 3: Push and create PR
```bash
# Push branch
git push origin feature/description

# Create PR (if gh CLI available)
gh pr create --title "feat: description" --body "## Changes\n- What changed\n\n## Testing\n- How tested"
```

### Step 4: Resolve conflicts
```bash
# Fetch latest
git fetch origin

# Rebase on main
git rebase origin/main

# Resolve conflicts in each file, then:
git add <resolved-file>
git rebase --continue

# Or abort if needed
git rebase --abort
```

### Step 5: Clean up after merge
```bash
# Switch to main and pull
git checkout main && git pull origin main

# Delete merged branch
git branch -d feature/description
git push origin --delete feature/description
```

## Tool Usage
- `terminal` for all git operations

## Pitfalls
1. Don't commit directly to main — always use feature branches
2. Don't force push shared branches — use `--force-with-lease` if needed
3. Don't commit secrets, credentials, or large binary files
4. Don't write vague commit messages — "fixed stuff" is useless
5. Don't leave uncommitted changes — commit or stash before switching branches

## Quick Reference
```bash
git checkout -b feature/name    # Create branch
git add -p                      # Stage interactively
git commit -m "type: message"   # Commit
git push origin feature/name    # Push
gh pr create                    # Create PR
git rebase origin/main          # Rebase
git branch -d feature/name      # Delete branch
```