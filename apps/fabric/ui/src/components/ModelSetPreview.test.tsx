// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelSetPreview } from "@/api/model-sets";
import { ModelSetPreviewDialog } from "./ModelSetPreview";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

function buildPreview(changeCount = 99): ModelSetPreview {
  return {
    companyId: "company-1",
    name: "openai-codex",
    source: "packaged",
    changes: Array.from({ length: changeCount }, (_, index) => ({
      agentId: `agent-${index + 1}`,
      agentName: `Agent ${index + 1}`,
      adapterType: "hermes_gateway",
      before: { provider: "openrouter", model: "old-model" },
      after: { provider: "openai-codex", model: "new-model" },
      family: "engineering",
      source: "profile",
    })),
  };
}

async function flushUi(callback?: () => void) {
  await act(async () => {
    callback?.();
    await Promise.resolve();
  });
}

describe("ModelSetPreviewDialog", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await flushUi(() => root.unmount());
    document.body.innerHTML = "";
  });

  it("keeps a large preview inside a viewport-bounded dialog with independent scrolling and a visible footer", async () => {
    await flushUi(() => {
      root.render(
        <ModelSetPreviewDialog
          open
          onOpenChange={() => {}}
          preview={buildPreview()}
          loading={false}
          applying={false}
          restartIdleGateways={false}
          onRestartIdleGatewaysChange={() => {}}
          onApply={() => {}}
        />,
      );
    });

    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement | null;
    expect(dialog).toBeTruthy();
    expect(dialog!.className).toContain("max-h-[calc(100dvh-2rem)]");
    expect(dialog!.className).toContain("overflow-hidden");
    expect(dialog!.className).toContain("flex-col");

    const previewRegion = dialog!.querySelector('[role="region"][aria-label="Agent model changes"]') as HTMLElement | null;
    expect(previewRegion).toBeTruthy();
    expect(previewRegion!.className).toContain("min-h-0");
    expect(previewRegion!.className).toContain("flex-1");
    expect(previewRegion!.className).toContain("overflow-auto");
    expect(previewRegion!.getAttribute("tabindex")).toBe("0");
    expect(previewRegion!.querySelectorAll("tbody tr")).toHaveLength(99);

    const footer = dialog!.querySelector('[data-slot="dialog-footer"]') as HTMLElement | null;
    expect(footer).toBeTruthy();
    expect(footer!.className).toContain("sticky");
    expect(footer!.className).toContain("bottom-0");
    expect(footer!.className).toContain("shrink-0");
    expect(previewRegion!.contains(footer)).toBe(false);
    expect(footer!.textContent).toContain("Cancel");
    expect(footer!.textContent).toContain("Apply now");
  });

  it("retains dialog semantics, Escape dismissal, and actionable controls", async () => {
    const onOpenChange = vi.fn();
    const onApply = vi.fn();

    await flushUi(() => {
      root.render(
        <ModelSetPreviewDialog
          open
          onOpenChange={onOpenChange}
          preview={buildPreview(1)}
          loading={false}
          applying={false}
          restartIdleGateways={false}
          onRestartIdleGatewaysChange={() => {}}
          onApply={onApply}
        />,
      );
    });

    const dialog = document.body.querySelector('[role="dialog"]') as HTMLElement;
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.getAttribute("aria-describedby")).toBeTruthy();

    const buttons = Array.from(dialog.querySelectorAll("button"));
    const applyButton = buttons.find((button) => button.textContent?.trim() === "Apply now");
    const cancelButton = buttons.find((button) => button.textContent?.trim() === "Cancel");

    await flushUi(() => applyButton?.click());
    expect(onApply).toHaveBeenCalledOnce();

    await flushUi(() => cancelButton?.click());
    expect(onOpenChange).toHaveBeenCalledWith(false);

    onOpenChange.mockClear();
    await flushUi(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
