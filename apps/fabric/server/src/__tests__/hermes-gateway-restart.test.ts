import { randomUUID } from "node:crypto";
import { agents, heartbeatRuns } from "@hermes-fabric/db";
import { afterEach, describe, expect, it, vi } from "vitest";
import { restartIdleGateways } from "../services/hermes-gateway-restart.js";

describe("restartIdleGateways", () => {
  const restartGateway = vi.fn(async () => undefined);

  afterEach(() => {
    restartGateway.mockReset();
  });

  it("restarts idle gateway agents and skips running agents with live runs", async () => {
    const companyId = randomUUID();
    const idleGatewayId = randomUUID();
    const runningGatewayId = randomUUID();

    const db = {
      select: vi.fn(() => ({
        from: (table: unknown) => {
          if (table === agents) {
            return {
              where: () => ({
                orderBy: async () => [
                  {
                    id: idleGatewayId,
                    companyId,
                    name: "agency-backend-engineer",
                    status: "idle",
                    adapterType: "hermes_gateway",
                    adapterConfig: { apiKey: "test-key" },
                  },
                  {
                    id: runningGatewayId,
                    companyId,
                    name: "agency-frontend-engineer",
                    status: "running",
                    adapterType: "hermes_gateway",
                    adapterConfig: { apiKey: "test-key" },
                  },
                ],
              }),
            };
          }
          if (table === heartbeatRuns) {
            return {
              where: async () => [{ agentId: runningGatewayId }],
            };
          }
          throw new Error("unexpected table");
        },
      })),
    } as any;

    const result = await restartIdleGateways(db, companyId, { deps: { restartGateway } });

    expect(result.attempted).toHaveLength(1);
    expect(result.attempted[0]?.agentId).toBe(idleGatewayId);
    expect(restartGateway).toHaveBeenCalledTimes(1);
    expect(restartGateway).toHaveBeenCalledWith({
      profileName: "agency-backend-engineer",
      hermesCommand: "hermes",
      apiKey: "test-key",
    });
    expect(result.skipped).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ agentId: runningGatewayId, reason: "agent_running" }),
      ]),
    );
  });
});