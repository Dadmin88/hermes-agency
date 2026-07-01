# Hermes Agency Discord Intake

Hermes Agency can poll a Discord channel and turn chat messages into orchestrator-owned tasks.

This is intentionally a polling MVP. It does not require a public webhook receiver or always-on bot loop inside the plugin. Run it manually, from cron, or from a user systemd timer.

## Configuration

The intake reuses the existing Discord bridge settings:

```bash
DISCORD_BOT_TOKEN=...
AGENTANYCAST_DISCORD_CHANNEL_ID=...
```

The channel ID can also be configured in Hermes config:

```yaml
agency:
  discord_channel_id: "123456789012345678"
```

Required sender allowlist (at least one Discord user ID or role ID must be configured before prefixed messages are queued):

```bash
HERMES_AGENCY_DISCORD_ALLOWED_USER_IDS=<discord-user-id>[,<discord-user-id>...]
HERMES_AGENCY_DISCORD_ALLOWED_ROLE_IDS=<discord-role-id>[,<discord-role-id>...]
```

or:

```yaml
agency:
  discord_allowed_user_ids:
    - "<discord-user-id>"
  discord_allowed_role_ids:
    - "<discord-role-id>"
```

Optional task prefix:

```bash
HERMES_AGENCY_DISCORD_TASK_PREFIX='!agency'
```

or:

```yaml
agency:
  discord_task_prefix: "!agency"
```

## Usage

Send a Discord message in the configured channel:

```text
!agency build the extended status dashboard
```

or:

```text
!agency task wire the orchestrator into Discord intake
```

Then poll:

```bash
hermes agency discord poll
```

Preview without queueing:

```bash
hermes agency discord poll --dry-run
```

Avoid posting acknowledgements back to Discord:

```bash
hermes agency discord poll --no-ack
```

## Behavior

Each matching message becomes:

- a Kanban task assigned to `agency-orchestrator`, when Kanban is available
- a local orchestrator tracking record
- a processed Discord message ID in `~/.hermes/agency/discord_intake_state.json`

The bot replies to Discord with a queued task acknowledgement unless `--no-ack` is passed.

## Notes

Only messages beginning with the configured prefix from an allowed Discord user ID or role ID are processed. Messages from bots are skipped to avoid loops. Treat allowed users and roles as a trusted command surface because accepted text is queued for the local orchestrator. Processed message IDs are retained to prevent duplicate task creation.
