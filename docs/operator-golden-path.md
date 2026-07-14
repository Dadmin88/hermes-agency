# Operator golden path

This is the shortest supported path from a clean Hermes install to a managed Agency workforce that can wake specialists, process trusted work, and report status.

Live multi-process Keryx proof remains `scripts/e2e_agency_keryx.py`. This document is the **operator** path for day-to-day use.

## Prerequisites

- Python 3.11+
- Hermes Agent installed (`hermes-agent>=0.18.0`)
- This package installed editable or from a release: `python -m pip install -e ".[dev]"`
- Optional for full remote transport: Keryx runtime binaries from `hermes-keryx` (`keryxd`, relay/registry as needed)

## 15-minute path

### 1. Install Agency into the active Hermes environment

```bash
python -m pip install -e ".[dev]"
hermes-agency --help
```

### 2. Install the starter staff pack (not all 83)

```bash
hermes-agency staff starter
hermes-agency staff install --starter --dry-run
hermes-agency staff install --starter
hermes-agency setup-plugins
```

Starter pack (12 profiles):

- `agency-orchestrator`
- `agency-chief-of-staff`
- `agency-product-manager`
- `agency-backend-engineer`
- `agency-frontend-engineer`
- `agency-code-reviewer`
- `agency-qa-tester`
- `agency-docs-writer`
- `agency-git-steward`
- `agency-devops-engineer`
- `agency-security-engineer`
- `agency-design-reviewer`

Install the full roster only when you need breadth:

```bash
hermes-agency staff install --dry-run
hermes-agency staff install
```

### 3. Choose a model set (dry-run first)

```bash
hermes-agency models list
hermes-agency models plan economic
hermes-agency models apply economic --dry-run
# when ready:
hermes-agency models apply economic --yes --backup
```

### 4. Configure Agency safely

In the orchestrator profile `config.yaml` (or root Hermes config with inheritance):

```yaml
agency:
  enabled: true
  transport_backend: keryx
  allow_remote_tasks: false   # leave false until you intentionally enable execution
  auto_start: false
  keryx:
    daemon_endpoint: 127.0.0.1:50051
    registry_endpoint: 127.0.0.1:51053
  incoming:
    tool_access: safe
  relay:
    allowlist: []            # empty = deny remote senders unless allow_all
```

Only open remote execution after trust/allowlist is intentional.

### 5. Doctor

```bash
hermes-agency doctor
hermes-agency doctor --json
```

Fix FAIL/WARN items until the report is acceptable for your environment. Starter pack and model-set drift appear as doctor checks.

### 6. Start and inspect

```bash
hermes-agency status --extended
hermes-agency start
hermes-agency status
hermes-agency registry
```

### 7. Prove a local delegation seam

Prefer the permanent in-process proof for CI/dev:

```bash
python -m pytest hermes-agency/tests/test_golden_path.py -q
```

For live Keryx multi-process proof (requires hermes-keryx binaries):

```bash
python scripts/e2e_agency_keryx.py --keryx-root <hermes-keryx-checkout> --work-dir .tmp/agency-phase17-e2e
```

### 8. Optional guided checklist script

```bash
python scripts/operator_golden_path.py --dry-run
python scripts/operator_golden_path.py
```

## Success criteria

| Step | Evidence |
|---|---|
| Starter pack installed | `hermes-agency staff starter` reports complete |
| Doctor | No unexpected FAIL for local single-host setup |
| Status | Node starts; peer id / transport backend reported when transport is available |
| Golden path test | `test_golden_path.py` passes |
| Live Keryx (optional) | `e2e_agency_keryx.py` returns terminal artifact |

## What this is not

- Hermes Fabric live dispatch (default Fabric client remains dry-run/unconfigured)
- Installing all 83 profiles on first boot
- Claiming production multi-tenant SaaS readiness

## Related

- `docs/plans/2026-07-13-hermes-agency-full-remediation.md`
- `docs/keryx-cross-node-boundary.md`
- `hermes-agency/README.md`
