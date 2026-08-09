# Operator Golden Path

This is the shortest supported path from a clean Hermes installation to a working Hermes Agency setup.

The goal is not to enable every feature at once. Start with a small local team, run the doctor checks, prove delegation, and only then enable remote work intentionally.

## Prerequisites

- Python 3.11+
- Hermes Agent 0.18.0+
- Hermes Agency installed from this repository
- Keryx runtime binaries only if you want the live cross-process transport proof

Install Agency for development:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Confirm the CLI is available:

```bash
hermes-agency --help
```

## Step 1: Install the starter staff

Start with the smaller starter group rather than installing every packaged specialist immediately.

```bash
hermes-agency staff install --starter --dry-run
hermes-agency staff install --starter
hermes-agency setup-plugins
```

You can inspect the starter profiles with:

```bash
hermes-agency staff starter
```

The starter set covers the common engineering and coordination roles needed to test Agency without filling the Hermes home with profiles you may never use.

Install the broader roster later if you actually need it.

## Step 2: Choose a model set

Model sets apply one provider/model strategy across the installed Agency staff.

Inspect first:

```bash
hermes-agency models list
hermes-agency models plan economic
```

Then dry-run the change:

```bash
hermes-agency models apply economic --dry-run
```

Apply only when the plan looks correct:

```bash
hermes-agency models apply economic --yes --backup
```

## Step 3: Start with conservative Agency settings

A safe starting configuration looks like this:

```yaml
agency:
  enabled: true
  transport_backend: keryx
  allow_remote_tasks: false
  auto_start: false
  keryx:
    daemon_endpoint: 127.0.0.1:50051
    registry_endpoint: 127.0.0.1:51053
  incoming:
    tool_access: safe
  relay:
    allowlist: []
```

The important defaults are:

- remote task execution stays disabled until you enable it intentionally;
- incoming tool access starts with the safe policy;
- an empty remote allowlist should not accidentally become broad trust.

Change those settings only after you understand which peers and tools you want to permit.

## Step 4: Run doctor

```bash
hermes-agency doctor
hermes-agency doctor --json
```

`doctor` is the first place to look when something is not ready. It checks the local setup, installed staff, model-set state, and transport-related configuration that Agency can validate safely.

Fix unexpected failures before moving on.

## Step 5: Start Agency and inspect it

```bash
hermes-agency status --extended
hermes-agency start
hermes-agency status
hermes-agency registry
```

At this point you should be able to see the local Agency state and, when transport is configured, the available registry/discovery information.

## Step 6: Prove local delegation

The permanent in-process golden-path test exercises real Agency modules with a controlled transport adapter:

```bash
python -m pytest hermes-agency/tests/test_golden_path.py -q
```

This is the best fast check for development because it proves Agency's own delegation, trust, artifact, and reconciliation seams without requiring a full live Keryx topology.

## Step 7: Optional live Keryx proof

If you have the Keryx Rust binaries available, run the live multi-process proof:

```bash
python scripts/e2e_agency_keryx.py \
  --keryx-root <hermes-keryx-checkout> \
  --work-dir .tmp/agency-keryx-e2e
```

This is a stronger test. It starts real Keryx processes and proves authenticated cross-process delivery and result return.

Do not describe the ordinary unit test suite as proof of this live path unless this E2E actually ran.

## Step 8: Optional guided helper

The repository also includes a guided operator helper:

```bash
python scripts/operator_golden_path.py --dry-run
python scripts/operator_golden_path.py
```

Use the dry-run first if you want to see what it plans to check or change.

## What success looks like

A basic working setup should have:

- the starter staff installed;
- no unexpected local `doctor` failures;
- Agency able to start and report status;
- the in-process golden-path test passing;
- optional live Keryx proof passing when cross-process transport is being tested.

## What this path does not prove

This setup does not automatically prove:

- production multi-tenant readiness;
- every packaged specialist works for every task;
- unrestricted remote execution is safe;
- Hermes Fabric live dispatch is configured;
- a live Keryx multi-machine path unless the live proof was actually run.

## Next reading

- [Keryx cross-node boundary](keryx-cross-node-boundary.md)
- [Agency model sets](agency-model-sets.md)
- [QA validation ladder](qa-validation-ladder.md)
- [Night Shift playbook](agency-night-shift-playbook.md)
