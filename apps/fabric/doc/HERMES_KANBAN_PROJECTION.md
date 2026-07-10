# Hermes Kanban projection

Hermes Fabric can project tasks from the Hermes Kanban SQLite board into Fabric issues so operators can view Agency work from the Fabric dashboard.

Kanban remains the source of truth. Fabric issue rows created by this sync are projections/caches, not the authoritative task record. Do not edit Fabric projected issue rows to change task state; update the Kanban task through Hermes Agency/Kanban tooling and let Fabric resync.

## Current VPS mapping

Use these values for the current DeployFaith VPS setup:

```sh
FABRIC_URL=http://100.123.57.115:3100
FABRIC_ENV_FILE=/home/dadmin/.paperclip/instances/default/hermes-fabric.env
FABRIC_HERMES_KANBAN_DB=/home/dadmin/.hermes/kanban.db
FABRIC_HERMES_KANBAN_COMPANY_ID=ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1
```

Company:

- Name: `DeployFaith`
- ID: `ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1`

The env file may contain other runtime settings. Do not paste the whole file into tickets, docs, or chat because it can also carry secrets in some deployments.

## What gets projected

On issue-list requests and on the projection status endpoint, Fabric reads the configured Kanban DB and upserts one Fabric issue per non-archived Kanban task into the configured company.

Projected rows use:

- `originKind`: `hermes_kanban_task`
- `originId`: the Kanban task ID, for example `t_d07e5951`
- `originFingerprint`: `hermes-kanban:<task-id>`

Fabric maps Kanban fields as follows:

| Kanban field | Fabric projection |
| --- | --- |
| `title` | issue title |
| `status` | issue status (`running` -> `in_progress`, `blocked` -> `blocked`, `done` -> `done`, `todo`/`ready` -> `todo`) |
| numeric `priority` | issue priority (`>=90` critical, `>=70` high, `>=40` medium, otherwise low) |
| `assignee` | `executionAgentNameKey` |
| `task_links` parent -> child | Fabric blocking relationships |

By default, projected issue descriptions include only low-risk metadata:

- Kanban task ID
- status
- priority
- assignee, when present
- block kind, when present

Fabric hides stale projections when a task disappears from the current Kanban snapshot or becomes archived. It does not delete the old Fabric issue row.

## Source-of-truth boundary

Use this boundary during operations:

1. Use Hermes Kanban as the authoritative record for task lifecycle, task body, comments, runs, results, blockers, and workspace paths.
2. Use Fabric projections for operator visibility, filtering, dependency display, and handoff awareness.
3. Treat projected Fabric rows as read-through cache entries. They may be re-created or hidden by sync.
4. Do not store secrets in Kanban task bodies or run metadata if `FABRIC_HERMES_KANBAN_INCLUDE_DETAILS=true` is enabled, because that setting copies more task details into Fabric issue descriptions.

## Required environment variables

Set these in `/home/dadmin/.paperclip/instances/default/hermes-fabric.env` for the current VPS:

```sh
HOST=100.123.57.115
PORT=3100
FABRIC_HERMES_KANBAN_DB=/home/dadmin/.hermes/kanban.db
FABRIC_HERMES_KANBAN_COMPANY_ID=ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1
```

Optional:

```sh
# Leave unset for the safer default.
# Set only when operators intentionally want task bodies, workspace paths,
# tenant labels, run summaries/errors, block reasons, and task results copied
# into Fabric projected issue descriptions.
FABRIC_HERMES_KANBAN_INCLUDE_DETAILS=false
```

Compatibility aliases:

- `PAPERCLIP_HERMES_KANBAN_DB` is accepted as a fallback for `FABRIC_HERMES_KANBAN_DB`.
- `PAPERCLIP_HERMES_KANBAN_COMPANY_ID` is accepted as a fallback for `FABRIC_HERMES_KANBAN_COMPANY_ID`.
- `PAPERCLIP_HERMES_KANBAN_INCLUDE_DETAILS` is accepted as a fallback for `FABRIC_HERMES_KANBAN_INCLUDE_DETAILS`.
- Unprefixed `HERMES_KANBAN_DB`, `HERMES_KANBAN_COMPANY_ID`, and `HERMES_KANBAN_INCLUDE_DETAILS` are also read by the current server code, but prefer the `FABRIC_` names for this deployment.

Both `FABRIC_HERMES_KANBAN_DB` and `FABRIC_HERMES_KANBAN_COMPANY_ID` are required. Without both, Fabric leaves Hermes tasks unprojected and returns `X-Hermes-Kanban-Sync: unavailable` with `X-Hermes-Kanban-Sync-Message`.

## Restart commands

From the Fabric app checkout:

```sh
cd /home/dadmin/repos/Hermes_Agency/apps/fabric

# Confirm the projection env file exists without printing secret-bearing values.
test -f /home/dadmin/.paperclip/instances/default/hermes-fabric.env
python3 - <<'PY'
from pathlib import Path
p = Path('/home/dadmin/.paperclip/instances/default/hermes-fabric.env')
for key in ['HOST', 'PORT', 'FABRIC_HERMES_KANBAN_DB', 'FABRIC_HERMES_KANBAN_COMPANY_ID', 'FABRIC_HERMES_KANBAN_INCLUDE_DETAILS']:
    for line in p.read_text(errors='replace').splitlines():
        if line.startswith(key + '='):
            print(line)
PY

# Stop the managed dev runner for this checkout, if it is running.
pnpm dev:stop

# Start Fabric with the instance env loaded.
set -a
. /home/dadmin/.paperclip/instances/default/hermes-fabric.env
set +a
pnpm dev --bind lan
```

If another process already owns the port, stop stale Fabric/Paperclip runners before restarting:

```sh
pkill -f "paperclip" || true
pkill -f "tsx.*index.ts" || true
```

Use the `pkill` fallback only when you know this VPS is dedicated to this Fabric instance.

## Verification commands

Basic service health:

```sh
curl -i http://100.123.57.115:3100/api/health
```

Projection status endpoint:

```sh
curl -i http://100.123.57.115:3100/api/hermes-agency/kanban-projection/status
```

Expected successful JSON shape:

```json
{
  "enabled": true,
  "dbPath": "/home/dadmin/.hermes/kanban.db",
  "companyId": "ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1",
  "lastSyncAt": "<ISO timestamp>",
  "lastStatus": "ok",
  "projectedCount": 1,
  "syncedCount": 1,
  "lastError": null
}
```

The exact `projectedCount` and `syncedCount` change with board state. `syncedCount` can be `0` on an idempotent sync when nothing changed.

Issue-list responses also include sync headers:

```sh
curl -i "http://100.123.57.115:3100/api/companies/ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1/issues?limit=20" \
  | grep -i '^X-Hermes-Kanban-Sync'
```

Expected healthy headers:

```text
X-Hermes-Kanban-Sync: ok
```

If the Fabric instance is in authenticated mode, run these `curl` commands from a session that includes valid board auth, or use the browser developer tools/network panel while signed in. A local implicit/dev session may not require a cookie; an authenticated/private session does.

## Troubleshooting

### Header says unavailable

Symptom:

```text
X-Hermes-Kanban-Sync: unavailable
X-Hermes-Kanban-Sync-Message: Hermes Kanban projection requires explicit FABRIC_HERMES_KANBAN_DB and FABRIC_HERMES_KANBAN_COMPANY_ID ...
```

Fix:

1. Confirm the env file contains both required variables:

   ```sh
   grep -E '^(FABRIC_HERMES_KANBAN_DB|FABRIC_HERMES_KANBAN_COMPANY_ID)=' /home/dadmin/.paperclip/instances/default/hermes-fabric.env
   ```

2. Restart Fabric after editing the env file. Environment changes are not picked up by an already-running Node process.
3. Re-run the projection status endpoint.

### Wrong company or empty projection

Symptoms:

- Projection status reports `enabled: true`, but the current company does not show projected tasks.
- Logs or headers say projection is scoped to a different company.
- Status endpoint reports `Configured Hermes Kanban company <id> was not found in Fabric.`

Fix:

1. Verify the configured company ID:

   ```sh
   grep '^FABRIC_HERMES_KANBAN_COMPANY_ID=' /home/dadmin/.paperclip/instances/default/hermes-fabric.env
   ```

2. Confirm it is the current DeployFaith ID:

   ```text
   ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1
   ```

3. Sign in as an instance admin or as a board user with access to that company.
4. Restart Fabric and reload the company board.

Fabric intentionally projects Kanban tasks into one configured company only. It skips unrelated companies to avoid leaking task data across company boundaries.

### Missing Kanban DB

Symptom:

```text
Hermes Kanban DB not found: /home/dadmin/.hermes/kanban.db
```

Fix:

```sh
test -r /home/dadmin/.hermes/kanban.db
sqlite3 /home/dadmin/.hermes/kanban.db '.tables'
```

If the file is missing, confirm Hermes Agency/Kanban is using the same home directory and board database. If permissions fail, run Fabric as a user that can read the Kanban DB or adjust file permissions without exposing the DB to other users unnecessarily.

### Schema mismatch

Symptom:

```text
Hermes Kanban DB schema mismatch: no such table: tasks
Hermes Kanban DB schema mismatch: no such column: ...
```

Fix:

1. Confirm the file is really the Hermes Kanban SQLite DB, not Fabric's embedded PostgreSQL directory or another SQLite file.
2. Check the expected tables:

   ```sh
   sqlite3 /home/dadmin/.hermes/kanban.db '.schema tasks'
   sqlite3 /home/dadmin/.hermes/kanban.db '.schema task_runs'
   sqlite3 /home/dadmin/.hermes/kanban.db '.schema task_events'
   sqlite3 /home/dadmin/.hermes/kanban.db '.schema task_links'
   ```

3. If Hermes Agency was upgraded, run the appropriate Hermes Kanban migration/repair path before restarting Fabric.

### Auth or session issues

Symptoms:

- `/api/hermes-agency/kanban-projection/status` returns `401` or redirects to sign-in.
- It returns `403` with `User does not have access to this company`.

Fix:

1. Sign in to Fabric as an instance admin or a user with access to the configured company.
2. Confirm the request is going to the same origin and port as the browser session: `http://100.123.57.115:3100`.
3. If using `curl`, include a valid session cookie or use a board-auth context. Do not paste cookies into docs, tickets, or chat.

### Mobile viewport caveat

The projection runs on the server and is independent of viewport size. However, the mobile tasks view can hide or compress columns and toolbar controls. When verifying projected tasks on a phone-width viewport, also check one of these surfaces:

- desktop-width board view
- issue list search/filter results
- the projection status endpoint
- issue detail metadata for a projected task

### Projected issue looks stale

Fix:

1. Hit the projection status endpoint to force a sync:

   ```sh
   curl -i http://100.123.57.115:3100/api/hermes-agency/kanban-projection/status
   ```

2. Reload the issue list for the configured company.
3. Check `lastSyncAt`, `lastStatus`, `projectedCount`, and `syncedCount`.
4. Remember that removed or archived Kanban tasks are hidden in Fabric rather than deleted.

## Safety checklist

Before handing off or publishing setup notes:

- Do not include session cookies, API keys, bearer tokens, database passwords, or password hashes.
- Do not paste the entire env file.
- Keep `FABRIC_HERMES_KANBAN_INCLUDE_DETAILS` unset or `false` unless operators explicitly accept copying richer Kanban task details into Fabric issue descriptions.
- State that Kanban is the source of truth and Fabric issue rows are projections/caches.
