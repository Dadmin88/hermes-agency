// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { HermesKanbanProjectionStatus } from "@paperclipai/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HermesAgencySettings } from "./HermesAgencySettings";

const mockHermesAgencyApi = vi.hoisted(() => ({
  kanbanProjectionStatus: vi.fn(),
}));
const mockSetBreadcrumbs = vi.hoisted(() => vi.fn());

vi.mock("@/api/hermesAgency", () => ({
  hermesAgencyApi: mockHermesAgencyApi,
}));

vi.mock("@/context/BreadcrumbContext", () => ({
  useBreadcrumbs: () => ({ setBreadcrumbs: mockSetBreadcrumbs }),
}));

vi.mock("@/context/CompanyContext", () => ({
  useCompany: () => ({
    companies: [
      { id: "company-deployfaith", name: "DeployFaith", issuePrefix: "DF" },
      { id: "company-other", name: "OtherCo", issuePrefix: "OTH" },
    ],
  }),
}));

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

function makeStatus(overrides: Partial<HermesKanbanProjectionStatus> = {}): HermesKanbanProjectionStatus {
  return {
    enabled: true,
    dbPath: "/home/dadmin/.hermes/kanban.db",
    companyId: "company-deployfaith",
    lastSyncAt: "2026-07-10T03:00:00.000Z",
    lastStatus: "ok",
    projectedCount: 12,
    syncedCount: 3,
    lastError: null,
    ...overrides,
  };
}

async function flushReact() {
  for (let index = 0; index < 5; index += 1) {
    await Promise.resolve();
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  }
}

async function renderPage() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <HermesAgencySettings />
      </QueryClientProvider>,
    );
  });
  await flushReact();
  return { container, root };
}

describe("HermesAgencySettings", () => {
  let roots: Root[] = [];

  beforeEach(() => {
    mockHermesAgencyApi.kanbanProjectionStatus.mockReset();
    mockSetBreadcrumbs.mockClear();
  });

  afterEach(async () => {
    await act(async () => {
      roots.forEach((root) => root.unmount());
    });
    roots = [];
    document.body.innerHTML = "";
  });

  it("shows the current DeployFaith Kanban projection mapping", async () => {
    mockHermesAgencyApi.kanbanProjectionStatus.mockResolvedValue(makeStatus());

    const { container, root } = await renderPage();
    roots.push(root);

    expect(container.textContent).toContain("Hermes Agency");
    expect(container.textContent).toContain("Kanban projection");
    expect(container.textContent).toContain("Last sync OK");
    expect(container.textContent).toContain("/home/dadmin/.hermes/kanban.db");
    expect(container.textContent).toContain("DeployFaith (DF)");
    expect(container.textContent).toContain("Read-only projection");
    expect(container.textContent).toContain("12");
    expect(container.textContent).toContain("3");

    const toggle = container.querySelector<HTMLButtonElement>('button[aria-label="Hermes Kanban projection enabled"]');
    expect(toggle?.getAttribute("aria-checked")).toBe("true");
    expect(toggle?.disabled).toBe(true);

    const companySelect = container.querySelector<HTMLSelectElement>("#hermes-kanban-company");
    expect(companySelect?.disabled).toBe(true);
    expect(companySelect?.value).toBe("company-deployfaith");
  });

  it("surfaces config and sync errors", async () => {
    mockHermesAgencyApi.kanbanProjectionStatus.mockResolvedValue(makeStatus({
      lastStatus: "error",
      lastError: "Hermes Kanban DB not found: /missing/kanban.db",
      dbPath: "/missing/kanban.db",
      projectedCount: 0,
      syncedCount: 0,
    }));

    const { container, root } = await renderPage();
    roots.push(root);

    expect(container.textContent).toContain("Sync error");
    expect(container.textContent).toContain("Hermes Kanban DB not found: /missing/kanban.db");
  });

  it("uses the status endpoint as the manual sync action", async () => {
    mockHermesAgencyApi.kanbanProjectionStatus.mockResolvedValue(makeStatus());

    const { container, root } = await renderPage();
    roots.push(root);

    const syncButton = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Sync now"),
    );
    expect(syncButton).toBeTruthy();

    await act(async () => {
      syncButton?.click();
    });
    await flushReact();

    expect(mockHermesAgencyApi.kanbanProjectionStatus).toHaveBeenCalledTimes(2);
  });

  it("shows request failures as visible errors", async () => {
    mockHermesAgencyApi.kanbanProjectionStatus.mockRejectedValue(new Error("status unavailable"));

    const { container, root } = await renderPage();
    roots.push(root);

    expect(container.textContent).toContain("status unavailable");
  });
});
