---
name: pr-preparation
description: Prepare a pull request from reviewed Git state with a minimal coherent diff, correct base/head, accurate summary, validation evidence, migration or risk notes, and no unrelated or stale changes.
---
# Pull Request Preparation

Use when a branch or commit series is ready to be proposed for integration through a pull request.

## Procedure
1. Verify the intended repository, base branch, head branch, remote ownership, and branch protection/review conventions before opening or updating the PR.
2. Compare head against the actual target base and inspect the full PR diff/file list, not just the last commit. Remove or split unrelated changes before asking reviewers to reason about them.
3. Ensure commits are coherent enough for the repository's review style and that generated/lockfile/migration/vendor changes are intentional and explained when non-obvious.
4. Update from the target base according to project policy when necessary and resolve conflicts before review if that reduces noise without rewriting shared history improperly.
5. Run or gather the validation appropriate to the proposed change and record exact commands/results or links. Do not claim tests/checks that were not actually run or whose environment was materially incomplete.
6. Write a PR title and summary describing the resulting behavior and motivation. Include important implementation choices only when they help reviewers understand the change or tradeoff.
7. Call out migrations, compatibility changes, rollout/rollback needs, security implications, known limitations, screenshots/demos, follow-up work, or manual validation when they materially affect review or release.
8. Link issues/tasks/designs/specifications that define the accepted intent where useful, but keep the PR body self-contained enough to understand the change.
9. Request reviewers appropriate to the affected domains and repository policy. Do not use reviewer count as a substitute for selecting people/profiles with relevant ownership.
10. After creation/update, verify the PR points at the intended head SHA/base and that CI/status checks correspond to that revision.

## Decision rules
- A PR is a review surface, not a development diary.
- The complete base-to-head diff is what reviewers approve, even if individual commits look clean.
- Do not hide known risk or incomplete validation to make the PR appear ready.
- Avoid giant prose templates when a concise summary, evidence, and risk notes communicate everything material.
- Reviewer selection should follow affected ownership and risk.

## Quality gate
The PR is ready when its diff is coherent and free of unrelated work, base/head are correct, validation evidence is truthful and revision-specific, material migration/risk/rollout information is visible, the description explains the resulting change, and reviewers can evaluate it without reconstructing the branch history themselves.