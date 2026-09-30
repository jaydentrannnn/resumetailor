// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { AttentionItem } from "../../api";
import { AttentionList } from "./AttentionList";

afterEach(cleanup);

describe("AttentionList", () => {
  it("counts outcomes and links the newest item first to its review tab", () => {
    const items: AttentionItem[] = [
      {
        application_id: "old",
        label: "Alpha — Engineer",
        kind: "failed",
        message: "Timed out",
        at: "2026-09-29T00:00:00Z",
      },
      {
        application_id: "new",
        label: "Beta — Designer",
        kind: "ready_for_review",
        message: "Ready to submit — final check",
        at: "2026-09-30T00:00:00Z",
      },
      {
        application_id: "middle",
        label: "Gamma — Writer",
        kind: "needs_input",
        message: "Enter code",
        at: "2026-09-29T12:00:00Z",
      },
    ];
    render(
      <MemoryRouter>
        <AttentionList items={items} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Needs attention \(3\)/).textContent).toContain(
      "1 error · 1 need review · 1 ready for final check",
    );
    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Beta — Designer",
      "Gamma — Writer",
      "Alpha — Engineer",
    ]);
    expect(links[0].getAttribute("href")).toBe("/applications/new?tab=review");
    expect(screen.getByText(/Gamma — Writer/).parentElement?.textContent).toContain(
      "needs review: Enter code",
    );
  });
});
