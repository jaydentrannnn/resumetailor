// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CapturedItem } from "../api";
import { CapturedBadge, filterCaptured, NeedsDescriptionGroup } from "./CapturedStubs";

afterEach(() => cleanup());

const listExtensionCaptures = vi.fn();
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  listExtensionCaptures: (stubsOnly: boolean) => listExtensionCaptures(stubsOnly),
}));

const stub: CapturedItem = {
  id: "linkedin:jobs:111",
  link_id: "ext-0123456789abcdef",
  company: "Acme",
  role: "Summer Analyst",
  location: "New York, NY",
  status: "discovered",
  site: "linkedin",
  posting_url: "https://www.linkedin.com/jobs/view/111/",
  capture_stub: true,
  apply_kind: "unknown",
  discovered_at: "2026-09-29T00:00:00Z",
};

describe("captured rows", () => {
  it("filters to rows the extension added", () => {
    const rows = [
      { sources: ["extension"] },
      { sources: ["simplify"] },
      { sources: ["simplify", "extension"] },
    ];
    expect(filterCaptured(rows, false)).toHaveLength(3);
    expect(filterCaptured(rows, true)).toEqual([rows[0], rows[2]]);
  });

  it("labels captured rows only", () => {
    const { container, rerender } = render(<CapturedBadge row={{ sources: ["simplify"] }} />);
    expect(container.textContent).toBe("");
    rerender(<CapturedBadge row={{ sources: ["extension"], capture_stub: true }} />);
    expect(screen.getByText("Captured · needs description")).toBeTruthy();
  });
});

describe("NeedsDescriptionGroup", () => {
  it("lists stubs with a link to open each on its board", async () => {
    listExtensionCaptures.mockResolvedValue([stub]);
    render(
      <MemoryRouter>
        <NeedsDescriptionGroup />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Needs description (1)")).toBeTruthy();
    expect(listExtensionCaptures).toHaveBeenCalledWith(true);
    const open = screen.getByRole("link", { name: /Open on LinkedIn/ });
    expect(open.getAttribute("href")).toBe(stub.posting_url);
    expect(screen.getByRole("link", { name: "Summer Analyst" }).getAttribute("href")).toBe(
      "/applications/ext-0123456789abcdef",
    );
  });

  it("renders nothing when there are no stubs", async () => {
    listExtensionCaptures.mockResolvedValue([]);
    const { container } = render(
      <MemoryRouter>
        <NeedsDescriptionGroup />
      </MemoryRouter>,
    );
    await Promise.resolve();
    expect(container.textContent).toBe("");
  });
});
