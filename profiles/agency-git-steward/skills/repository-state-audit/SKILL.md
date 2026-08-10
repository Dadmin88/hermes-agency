---
name: repository-state-audit
description: Audit exact Git repository state across branch, HEAD, index, working tree, untracked files, remotes, divergence, worktrees, submodules, and reachable commits before consequential source-control operations.
---
# Repository State Audit

Use before merges, rebases, resets, releases, history rewrites, cleanup, handoff, or whenever the repository's true state must be known precisely.

## Procedure
1. Identify repository root and active worktree. Record current branch or detached HEAD, exact commit SHA, and whether an operation such as rebase/merge/cherry-pick/bisect is in progress.
2. Inspect working tree and index separately: staged changes, unstaged changes, untracked/ignored files relevant to the task, conflicts, intent-to-add, deletions, renames, and submodule state where used.
3. Inspect branch upstream/tracking configuration and remotes. Confirm which remote and branch are authoritative for the intended operation rather than assuming `origin/main`.
4. Fetch or otherwise refresh remote refs when current remote state is necessary and network policy allows it. Then record ahead/behind/divergence and merge-base relationships relevant to the task.
5. Inspect linked worktrees and branches checked out elsewhere so a cleanup, branch move, or rebase does not collide with active work on another path/process/agent.
6. Identify commits or changes at risk of becoming unreachable before reset/delete/history rewrite. Preserve a named branch/tag or exact SHA when recovery would otherwise depend on reflog luck.
7. Inspect stash state if the workflow uses it, but do not assume stashes contain only the current task or are safe to drop/apply blindly.
8. For release/checkpoint work, verify the exact tree/content being claimed: commit tree, tags, branch pointers, submodule revisions, generated artifacts, and remote parity as required by the project's assurance level.
9. Report the state compactly with exact identifiers and any hazard: uncommitted work, divergence, stale remote knowledge, conflict operation, unexpected worktree, missing upstream, or commits not safely referenced.
10. Make no destructive change as part of the audit unless the assignment separately authorizes remediation.

## Decision rules
- Working tree, index, commit, branch ref, and remote ref are different states; never conflate them.
- `git status` alone is useful but may not answer remote divergence, worktree ownership, or exact tree identity.
- Refresh remote refs only when the operation depends on current remote truth.
- An untracked file can be valuable work; “not in Git” does not mean disposable.
- Exact SHAs/tree IDs are preferable to vague claims such as “latest” for consequential handoffs.

## Quality gate
The audit is complete when current commit/branch, staged and unstaged work, untracked/conflicted state, remote/upstream relationship, relevant worktrees, and at-risk commits are known well enough that the next Git operation cannot honestly be described as proceeding from an assumed repository state.