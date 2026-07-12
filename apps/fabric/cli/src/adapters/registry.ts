import type { CLIAdapterModule } from "@hermes-fabric/adapter-utils";
import { printAcpxStreamEvent } from "@hermes-fabric/adapter-acpx-local/cli";
import { printClaudeStreamEvent } from "@hermes-fabric/adapter-claude-local/cli";
import { printCodexStreamEvent } from "@hermes-fabric/adapter-codex-local/cli";
import { printCursorStreamEvent } from "@hermes-fabric/adapter-cursor-local/cli";
import { printCursorCloudEvent } from "@hermes-fabric/adapter-cursor-cloud/cli";
import { printGeminiStreamEvent } from "@hermes-fabric/adapter-gemini-local/cli";
import { printGrokStreamEvent } from "@hermes-fabric/adapter-grok-local/cli";
import { formatStdoutEvent as printHermesGatewayStreamEvent } from "@hermes-fabric/hermes-fabric-adapter/gateway/cli";
import { printHermesStreamEvent } from "@hermes-fabric/hermes-fabric-adapter/cli";
import { printOpenCodeStreamEvent } from "@hermes-fabric/adapter-opencode-local/cli";
import { printPiStreamEvent } from "@hermes-fabric/adapter-pi-local/cli";
import { printOpenClawGatewayStreamEvent } from "@hermes-fabric/adapter-openclaw-gateway/cli";
import { processCLIAdapter } from "./process/index.js";
import { httpCLIAdapter } from "./http/index.js";

const claudeLocalCLIAdapter: CLIAdapterModule = {
  type: "claude_local",
  formatStdoutEvent: printClaudeStreamEvent,
};

const acpxLocalCLIAdapter: CLIAdapterModule = {
  type: "acpx_local",
  formatStdoutEvent: printAcpxStreamEvent,
};

const codexLocalCLIAdapter: CLIAdapterModule = {
  type: "codex_local",
  formatStdoutEvent: printCodexStreamEvent,
};

const openCodeLocalCLIAdapter: CLIAdapterModule = {
  type: "opencode_local",
  formatStdoutEvent: printOpenCodeStreamEvent,
};

const piLocalCLIAdapter: CLIAdapterModule = {
  type: "pi_local",
  formatStdoutEvent: printPiStreamEvent,
};

const cursorLocalCLIAdapter: CLIAdapterModule = {
  type: "cursor",
  formatStdoutEvent: printCursorStreamEvent,
};

const cursorCloudCLIAdapter: CLIAdapterModule = {
  type: "cursor_cloud",
  formatStdoutEvent: printCursorCloudEvent,
};

const geminiLocalCLIAdapter: CLIAdapterModule = {
  type: "gemini_local",
  formatStdoutEvent: printGeminiStreamEvent,
};

const grokLocalCLIAdapter: CLIAdapterModule = {
  type: "grok_local",
  formatStdoutEvent: printGrokStreamEvent,
};

const hermesGatewayCLIAdapter: CLIAdapterModule = {
  type: "hermes_gateway",
  formatStdoutEvent: printHermesGatewayStreamEvent,
};

const hermesLocalCLIAdapter: CLIAdapterModule = {
  type: "hermes_local",
  formatStdoutEvent: printHermesStreamEvent,
};

const openclawGatewayCLIAdapter: CLIAdapterModule = {
  type: "openclaw_gateway",
  formatStdoutEvent: printOpenClawGatewayStreamEvent,
};

const adaptersByType = new Map<string, CLIAdapterModule>(
  [
    acpxLocalCLIAdapter,
    claudeLocalCLIAdapter,
    codexLocalCLIAdapter,
    openCodeLocalCLIAdapter,
    piLocalCLIAdapter,
    cursorLocalCLIAdapter,
    cursorCloudCLIAdapter,
    geminiLocalCLIAdapter,
    grokLocalCLIAdapter,
    hermesGatewayCLIAdapter,
    hermesLocalCLIAdapter,
    openclawGatewayCLIAdapter,
    processCLIAdapter,
    httpCLIAdapter,
  ].map((a) => [a.type, a]),
);

export function getCLIAdapter(type: string): CLIAdapterModule {
  return adaptersByType.get(type) ?? processCLIAdapter;
}
