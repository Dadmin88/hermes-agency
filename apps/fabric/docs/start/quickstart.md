---
title: Quickstart
summary: Get Hermes Fabric running in minutes
---

Get Hermes Fabric running locally in under 5 minutes.

## Quick Start (Recommended)

```sh
npx hermes-fabric onboard --yes
```

This walks you through setup, configures your environment, and gets Hermes Fabric running.

If you already have a Hermes Fabric install, rerunning `onboard` keeps your current config and data paths intact. Use `hermes-fabric configure` if you want to edit settings.

To start Hermes Fabric again later:

```sh
npx hermes-fabric run
```

> **Note:** If you used `npx` for setup, always use `npx hermes-fabric` to run commands. The `pnpm hermes-fabric` form only works inside a cloned copy of the Hermes Fabric repository (see Local Development below).

## Local Development

For contributors working on Hermes Fabric itself. Prerequisites: Node.js 20+ and pnpm 9+.

Clone the repository, then:

```sh
pnpm install
pnpm dev
```

This starts the API server and UI at [http://localhost:3100](http://localhost:3100).

No external database required — Hermes Fabric uses an embedded PostgreSQL instance by default.

When working from the cloned repo, you can also use:

```sh
pnpm hermes-fabric run
```

This auto-onboards if config is missing, runs health checks with auto-repair, and starts the server.

## What's Next

Once Hermes Fabric is running:

1. Create your first company in the web UI
2. Define a company goal
3. Create a CEO agent and configure its adapter
4. Build out the org chart with more agents
5. Set budgets and assign initial tasks
6. Hit go — agents start their heartbeats and the company runs

<Card title="Core Concepts" href="/start/core-concepts">
  Learn the key concepts behind Hermes Fabric
</Card>
