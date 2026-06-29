# Hermes Fabric upstream sync

Hermes Fabric lives in this repository as the Hermes Agency frontend:

```text
apps/fabric/
```

It is derived from upstream Paperclip. Hermes Agency is the product boundary; Hermes Fabric is the frontend app/codename.

## Git remotes and branches

```text
origin              DeployFaith/Hermes_Agency
paperclip-upstream  https://github.com/paperclipai/paperclip.git
paperclip-vendor    clean local mirror of paperclip-upstream/master
```

Paperclip's current default branch is `master`, not `main`.

## Inspect upstream changes

```bash
git fetch paperclip-upstream '+refs/heads/*:refs/remotes/paperclip-upstream/*'
git log --oneline paperclip-vendor..paperclip-upstream/master
```

For a scoped diff:

```bash
git diff paperclip-vendor..paperclip-upstream/master -- \
  package.json \
  pnpm-lock.yaml \
  pnpm-workspace.yaml \
  cli \
  packages \
  server \
  ui
```

## Update the clean vendor branch

Do this only when intentionally reviewing or porting upstream Paperclip changes.

```bash
git fetch paperclip-upstream '+refs/heads/*:refs/remotes/paperclip-upstream/*'
git checkout paperclip-vendor
git merge --ff-only paperclip-upstream/master
git checkout -
```

`paperclip-vendor` should stay clean and should not contain Hermes Agency or `apps/fabric` edits.

## Port changes into Hermes Fabric

The imported app is stored under a prefix:

```text
apps/fabric/
```

Upstream Paperclip paths are root-relative, so raw cherry-picks may not apply cleanly. Prefer one of these workflows:

### Manual scoped port

1. Inspect upstream commits:

   ```bash
   git log --oneline paperclip-vendor..paperclip-upstream/master
   ```

2. Inspect a specific commit or range:

   ```bash
   git show --stat <commit>
   git show <commit> -- cli packages server ui
   ```

3. Manually port relevant changes into matching prefixed paths under `apps/fabric/`.

4. Run focused verification from `apps/fabric/`.

### Subtree-style batch port

Only use this after checking the upstream diff and accepting merge conflict risk:

```bash
git subtree pull --prefix=apps/fabric paperclip-upstream master --squash
```

If conflicts are broad, abort and fall back to manual scoped porting.

## Verification after porting

From the repository root:

```bash
cd apps/fabric
npm exec --yes pnpm@9.15.4 -- install --frozen-lockfile
npm exec --yes pnpm@9.15.4 -- -r typecheck
npm exec --yes pnpm@9.15.4 -- test:run
npm exec --yes pnpm@9.15.4 -- build
```

For narrow upstream ports, run the smallest affected package tests first, then broaden as needed.

## Public documentation rules

Keep docs generic. Do not commit maintainer-local paths, private hostnames, private IPs, private peer IDs, tokens, keys, or environment dumps. Use placeholders such as:

```text
<workspace>
<tailnet-hostname>
<relay-multiaddr>
<registry-address>
<profile-name>
```

## Commit hygiene

Before committing upstream sync work:

```bash
git diff --check
git status --short
```

Confirm staged changes are only intentional `apps/fabric/` frontend changes and any related repo docs.
