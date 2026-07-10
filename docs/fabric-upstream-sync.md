# Hermes Fabric upstream sync

Hermes Fabric lives under `apps/fabric/` as the operator interface for Hermes Agency.

The upstream-sync pipeline is designed to keep receiving useful source updates without reintroducing inherited branding, package scopes, environment prefixes, filenames, or user-facing copy.

## How the pipeline works

The scheduled or manually dispatched workflow at `.github/workflows/fabric-upstream-sync.yml` performs five stages:

1. Fetch the configured source repository and target ref.
2. Check out both the last imported source commit and the new target commit.
3. Normalize both snapshots into Hermes Fabric namespaces before diffing them.
4. Three-way merge the normalized update into the current `apps/fabric/` tree.
5. Open a draft pull request for normal CI, review, and merge.

The write-capable sync workflow does not install dependencies, run package scripts, or execute imported application code. Typecheck, tests, and build happen in ordinary pull-request CI.

## Repository variables

Configure these GitHub Actions repository variables:

| Variable | Purpose |
|---|---|
| `FABRIC_UPSTREAM_REPOSITORY` | Source repository in `owner/name` form. |
| `FABRIC_UPSTREAM_REF` | Source branch or tag. Defaults to `master` when unset. |
| `FABRIC_UPSTREAM_LEGACY_ALIASES` | Comma-separated source product-name aliases that must be normalized. |
| `FABRIC_UPSTREAM_LEGACY_SCOPES` | Comma-separated source package scopes that must become `@hermes-fabric/*`. |
| `FABRIC_UPSTREAM_BASE_SHA` | Optional first-run baseline when the tracked state has not yet been bootstrapped. |

The source identity remains in repository configuration rather than tracked source files.

## First-time bootstrap

The tracked state lives at:

```text
apps/fabric/.upstream/state.json
```

On the first run, trigger **Hermes Fabric Upstream Sync** manually with `bootstrap=true`. The workflow records the current source head as the baseline and opens a small draft PR. After that PR is merged, scheduled runs can detect and import later upstream commits.

Use `baseline_sha` instead of bootstrap when older source changes must be imported immediately.

## Normalization contract

`apps/fabric/scripts/normalize-upstream-import.py` converts the configured source aliases into:

- `Hermes Fabric` for product and interface language
- `Hermes Agency` for roster, team, execution, and orchestration concepts
- `@hermes-fabric/*` for workspace package scopes
- `HERMES_FABRIC_*` for environment and configuration prefixes
- `hermes-fabric` or `fabric` for CLI commands, package slugs, service names, and filenames

The normalizer runs on both the baseline and incoming source snapshots. This is important: the merge compares two already-normalized trees, so ordinary upstream edits apply to Hermes-named files instead of creating the inherited names again.

## Merge behavior

`apps/fabric/scripts/merge-upstream-snapshots.py` uses a real three-way merge:

- ancestor: normalized last-imported source snapshot
- ours: current Hermes Fabric tree
- theirs: normalized new source snapshot

Local-only Hermes files are untouched. Clean upstream changes are applied automatically. Files changed independently on both sides are merged with `git merge-file`.

When a conflict cannot be resolved safely:

- the tracked baseline is not advanced
- conflict evidence is written under `apps/fabric/.upstream/conflicts/`
- a draft PR is opened with the conflict report
- no imported package scripts are executed

After resolving the listed files, remove the conflict artifacts, update `state.json` to the target source commit, and run the normal Fabric checks.

## Verification

Every generated update PR must pass:

```bash
cd apps/fabric
pnpm run check:branding
pnpm run preflight:workspace-links
pnpm run typecheck
pnpm run test:run
pnpm run build
```

The rebrand guard also requires zero configured source aliases in tracked Fabric content or paths.

## Manual inspection

The sync PR records the baseline and target source commits. To inspect the raw source range outside the product repository:

```bash
git clone https://github.com/<source-owner>/<source-repository>.git /tmp/fabric-source
git -C /tmp/fabric-source diff <baseline-sha>..<target-sha>
```

Do not manually paste source branding into Hermes Fabric while resolving conflicts. Apply the same namespace rules used by the normalizer.
