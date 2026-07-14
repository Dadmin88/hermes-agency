# Hermes Fabric MCP Server

Model Context Protocol server for Hermes Fabric.

This package is a thin MCP wrapper over the existing Hermes Fabric REST API. It does
not talk to the database directly and it does not reimplement business logic.

## Authentication

The server reads its configuration from environment variables:

- `HERMES_FABRIC_API_URL` - Hermes Fabric base URL, for example `http://localhost:3100`
- `HERMES_FABRIC_API_KEY` - bearer token used for `/api` requests
- `HERMES_FABRIC_COMPANY_ID` - optional default company for company-scoped tools
- `HERMES_FABRIC_AGENT_ID` - optional default agent for checkout helpers
- `HERMES_FABRIC_RUN_ID` - optional run id forwarded on mutating requests

## Usage

```sh
npx -y @hermes-fabric/mcp-server
```

Or locally in this repo:

```sh
pnpm --filter @hermes-fabric/mcp-server build
node packages/mcp-server/dist/stdio.js
```

## Tool Surface

Read tools:

- `fabricMe`
- `fabricInboxLite`
- `fabricListAgents`
- `fabricGetAgent`
- `fabricListIssues`
- `fabricGetIssue`
- `fabricGetHeartbeatContext`
- `fabricListComments`
- `fabricGetComment`
- `fabricListIssueApprovals`
- `fabricListDocuments`
- `fabricGetDocument`
- `fabricListDocumentRevisions`
- `fabricListProjects`
- `fabricGetProject`
- `fabricGetIssueWorkspaceRuntime`
- `fabricWaitForIssueWorkspaceService`
- `fabricListGoals`
- `fabricGetGoal`
- `fabricListApprovals`
- `fabricGetApproval`
- `fabricGetApprovalIssues`
- `fabricListApprovalComments`

Write tools:

- `fabricCreateIssue`
- `fabricUpdateIssue`
- `fabricCheckoutIssue`
- `fabricReleaseIssue`
- `fabricAddComment`
- `fabricSuggestTasks`
- `fabricAskUserQuestions`
- `fabricRequestConfirmation`
- `fabricUpsertIssueDocument`
- `fabricRestoreIssueDocumentRevision`
- `fabricControlIssueWorkspaceServices`
- `fabricCreateApproval`
- `fabricLinkIssueApproval`
- `fabricUnlinkIssueApproval`
- `fabricApprovalDecision`
- `fabricAddApprovalComment`

Escape hatch:

- `fabricApiRequest`

`fabricApiRequest` is limited to paths under `/api` and JSON bodies. It is
meant for endpoints that do not yet have a dedicated MCP tool.
