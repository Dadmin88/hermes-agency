// @vitest-environment jsdom

import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { HermesAgencyAgent, HermesAgencyRosterResponse } from "@hermes-fabric/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HermesAgencyRoster } from "./HermesAgencyRoster";

const mockHermesAgencyApi = vi.hoisted(() => ({
  roster: vi.fn(),
  dispatch: vi.fn(),
}));
const mockSetBreadcrumbs = vi.hoisted(() => vi.fn());

vi.mock("../api/hermesAgency", () => ({ hermesAgencyApi: mockHermesAgencyApi }));
vi.mock("../context/BreadcrumbContext", () => ({
  useBreadcrumbs: () => ({ setBreadcrumbs: mockSetBreadcrumbs }),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

function makeAgent(overrides: Partial<HermesAgencyAgent> = {}): HermesAgencyAgent {
  return {
    name: "agency-backend-engineer",
    description: "Builds APIs and integrations.",
    skills: ["api", "typescript"],
    online: false,
    status: "offline",
    lastSeen: null,
    wakeAttempts: 0,
    lastAttempt: null,
    lastError: null,
    model: "gpt-5.5",
    provider: "openai-codex",
    ...overrides,
  };
}

function makeRoster(agents: HermesAgencyAgent[]): HermesAgencyRosterResponse {
  const online = agents.filter((agent) => agent.online).length;
  return {
    tenant: "default",
    filter: "agency-only",
    total: agents.length,
    online,
    offline: agents.length - online,
    agents,
  };
}

function makeLargeOfflineRoster(): HermesAgencyRosterResponse {
  const agents = Array.from({ length: 83 }, (_, index) => makeAgent({
    name: index === 0 ? "agency-backend-engineer" : `agency-specialist-${String(index).padStart(2, "0")}`,
    description: index === 0 ? "Builds APIs and integrations." : `Specialist ${index}`,
    skills: index === 0 ? ["api", "typescript"] : [index % 2 === 0 ? "design" : "research"],
    status: index === 0 ? "wake_failed" : "offline",
    lastError: index === 0 ? "Error: profile agency-backend-engineer not found" : null,
    wakeAttempts: index === 0 ? 2 : 0,
    lastAttempt: index === 0 ? "2026-06-29T10:00:00Z" : null,
  }));
  return makeRoster(agents);
}

async function flushReact() {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

function changeValue(element: HTMLInputElement | HTMLSelectElement, value: string) {
  const prototype = element instanceof HTMLInputElement
    ? window.HTMLInputElement.prototype
    : window.HTMLSelectElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

async function renderPage() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HermesAgencyRoster />
      </QueryClientProvider>,
    );
  });
  await flushReact();
  await flushReact();
  return { container, root, queryClient };
}

describe("HermesAgencyRoster", () => {
  let roots: Root[] = [];

  beforeEach(() => {
    mockSetBreadcrumbs.mockClear();
    mockHermesAgencyApi.roster.mockReset();
    mockHermesAgencyApi.dispatch.mockReset();
  });

  afterEach(async () => {
    await act(async () => {
      roots.forEach((root) => root.unmount());
    });
    roots = [];
    document.body.innerHTML = "";
  });

  it("shows the 83-agent offline roster and wake failures as actionable state", async () => {
    mockHermesAgencyApi.roster.mockResolvedValue(makeLargeOfflineRoster());

    const { container, root } = await renderPage();
    roots.push(root);

    expect(container.textContent).toContain("Hermes Agency roster");
    expect(container.textContent).toContain("83");
    expect(container.textContent).toContain("0 online");
    expect(container.textContent).toContain("83 offline");
    expect(container.textContent).toContain("1 wake failed");
    expect(container.textContent).toContain("agency-backend-engineer");
    expect(container.textContent).toContain("Offline target");
    const backendRow = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("agency-backend-engineer"),
    ) as HTMLButtonElement | undefined;
    expect(backendRow).toBeTruthy();
    await act(async () => {
      backendRow?.click();
    });
    await flushReact();
    expect(container.textContent).toContain("Error: profile agency-backend-engineer not found");
  });

  it("filters by name, skill, and wake-failed status", async () => {
    mockHermesAgencyApi.roster.mockResolvedValue(makeRoster([
      makeAgent({ name: "agency-backend-engineer", skills: ["api"], status: "wake_failed", lastError: "profile missing" }),
      makeAgent({ name: "agency-ui-ux-designer", description: "Designs polished UI.", skills: ["design"], status: "offline" }),
    ]));

    const { container, root } = await renderPage();
    roots.push(root);

    await act(async () => {
      changeValue(container.querySelector('input[aria-label="Search agents"]') as HTMLInputElement, "designer");
    });
    await flushReact();
    expect(container.textContent).toContain("agency-ui-ux-designer");
    expect(container.textContent).not.toContain("agency-backend-engineer");

    await act(async () => {
      changeValue(container.querySelector('input[aria-label="Search skills"]') as HTMLInputElement, "api");
      changeValue(container.querySelector('input[aria-label="Search agents"]') as HTMLInputElement, "");
      changeValue(container.querySelector('select[aria-label="Status filter"]') as HTMLSelectElement, "wake_failed");
    });
    await flushReact();

    expect(container.textContent).toContain("agency-backend-engineer");
    expect(container.textContent).not.toContain("agency-ui-ux-designer");
  });

  it("shows an error state when the roster API is unavailable", async () => {
    mockHermesAgencyApi.roster.mockRejectedValue(new Error("roster unavailable"));

    const { container, root } = await renderPage();
    roots.push(root);

    expect(container.textContent).toContain("Could not load Hermes Agency roster");
    expect(container.textContent).toContain("roster unavailable");
  });

  it("sends a skill-fit dispatch request from an agent card and shows queue status", async () => {
    mockHermesAgencyApi.roster.mockResolvedValue(makeRoster([
      makeAgent({ name: "agency-backend-engineer", skills: ["api", "typescript"], status: "offline" }),
    ]));
    mockHermesAgencyApi.dispatch.mockResolvedValue({
      id: "dispatch-1",
      createdAt: "2026-06-29T10:00:00Z",
      updatedAt: "2026-06-29T10:00:00Z",
      mode: "skill-fit",
      skill: "api",
      targetAgentName: null,
      taskId: null,
      queueId: "offline-queue-1",
      status: "queued",
      message: "queued",
      artifacts: [],
      statusHistory: [{ status: "queued", at: "2026-06-29T10:00:00Z", message: "queued" }],
      packet: {},
      raw: null,
    });

    const { container, root } = await renderPage();
    roots.push(root);

    const agentRow = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("agency-backend-engineer"),
    ) as HTMLButtonElement | undefined;
    const taskControls = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.trim() === "Task controls",
    ) as HTMLButtonElement | undefined;
    expect(agentRow).toBeTruthy();
    expect(taskControls).toBeTruthy();
    await act(async () => {
      agentRow?.click();
      taskControls?.click();
    });
    await flushReact();
    const sendTask = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Send task"),
    ) as HTMLButtonElement | undefined;
    expect(sendTask).toBeTruthy();
    await act(async () => {
      sendTask?.click();
    });
    await flushReact();

    expect(mockHermesAgencyApi.dispatch).toHaveBeenCalledWith(expect.objectContaining({
      mode: "skill-fit",
      packet: expect.objectContaining({
        targetAgentName: "agency-backend-engineer",
        requestedSkills: ["api", "typescript"],
      }),
    }));
    expect(container.textContent).toContain("Latest dispatch");
    expect(container.textContent).toContain("queued");
    expect(container.textContent).toContain("offline-queue-1");
  });
});
