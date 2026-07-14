#!/usr/bin/env node
import { runServer } from "./index.js";

void runServer().catch((error) => {
  console.error("Failed to start HermesFabric MCP server:", error);
  process.exit(1);
});
