import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { HermesFabricApiClient } from "./client.js";
import { readConfigFromEnv, type HermesFabricMcpConfig } from "./config.js";
import { createToolDefinitions } from "./tools.js";

export function createHermesFabricMcpServer(config: HermesFabricMcpConfig = readConfigFromEnv()) {
  const server = new McpServer({
    name: "fabric",
    version: "0.1.0",
  });

  const client = new HermesFabricApiClient(config);
  const tools = createToolDefinitions(client);
  for (const tool of tools) {
    server.tool(tool.name, tool.description, tool.schema.shape, tool.execute);
  }

  return {
    server,
    tools,
    client,
  };
}

export async function runServer(config: HermesFabricMcpConfig = readConfigFromEnv()) {
  const { server } = createHermesFabricMcpServer(config);
  const transport = new StdioServerTransport();
  await server.connect(transport);
}
