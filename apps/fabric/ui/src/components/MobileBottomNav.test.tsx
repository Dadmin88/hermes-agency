// @vitest-environment jsdom

import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MobileBottomNav } from "./MobileBottomNav";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const mockOpenNewIssue = vi.hoisted(() => vi.fn());
const mockUseLocation = vi.hoisted(() => vi.fn());
const mockUseInboxBadge = vi.hoisted(() => vi.fn());

vi.mock("@/lib/router", () => ({
  NavLink: ({ children, to, className, ...props }: {
    children: ReactNode | ((state: { isActive: boolean }) => ReactNode);
    to: string;
    className?: string | ((state: { isActive: boolean }) => string);
  }) => {
    const isActive = false;
    return (
      <a
        href={to}
        className={typeof className === "function" ? className({ isActive }) : className}
        {...props}
      >
        {typeof children === "function" ? children({ isActive }) : children}
      </a>
    );
  },
  useLocation: () => mockUseLocation(),
}));

vi.mock("../context/CompanyContext", () => ({
  useCompany: () => ({ selectedCompanyId: "company-1" }),
}));

vi.mock("../context/DialogContext", () => ({
  useDialogActions: () => ({ openNewIssue: mockOpenNewIssue }),
}));

vi.mock("../hooks/useInboxBadge", () => ({
  useInboxBadge: (companyId: string | null | undefined) => mockUseInboxBadge(companyId),
}));

describe("MobileBottomNav", () => {
  let container: HTMLDivElement;
  let root: Root;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root.unmount();
      });
    }
    container?.remove();
    vi.clearAllMocks();
  });

  it("routes the Agents tab to the Hermes Agency roster", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mockUseLocation.mockReturnValue({ pathname: "/dashboard" });
    mockUseInboxBadge.mockReturnValue({ inbox: 0 });

    await act(async () => {
      root.render(<MobileBottomNav visible />);
    });

    const agentsLink = Array.from(container.querySelectorAll("a")).find((anchor) =>
      anchor.textContent?.includes("Agents"),
    );

    expect(agentsLink?.getAttribute("href")).toBe("/agency-roster");
  });
});
