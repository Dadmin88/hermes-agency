// @vitest-environment jsdom

import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { FabricParticleTopology, fabricParticleTopologySample, summarizeTopology } from "./FabricParticleTopology";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function render(element: ReactNode) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root?.render(element);
  });
  return container;
}

afterEach(async () => {
  await act(async () => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  container = null;
});

describe("FabricParticleTopology", () => {
  it("summarizes the curated sample topology statuses", () => {
    expect(summarizeTopology(fabricParticleTopologySample)).toEqual({
      online: 3,
      queued: 2,
      offline: 0,
      blocked: 1,
    });
  });

  it("renders an accessible static visualization with no WebGL dependency", async () => {
    const view = await render(<FabricParticleTopology />);

    expect(view.querySelector("svg[role='img']")).not.toBeNull();
    expect(view.textContent).toContain("Keryx task-flow topology");
    expect(view.textContent).toContain("No WebGL required");
    expect(view.textContent).toContain("No arbitrary generated JS");
  });
});
