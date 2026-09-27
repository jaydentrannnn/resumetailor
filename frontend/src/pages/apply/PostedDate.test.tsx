// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ApplicationRow } from "../../api";
import { localDate } from "../../lib/applicationRows";
import { PostedDate } from "./ApplicationsTable";

const row = (fields: Partial<ApplicationRow>) =>
  ({ discovered_at: "2026-09-20T10:00:00+00:00", ...fields }) as ApplicationRow;

afterEach(cleanup);

describe("PostedDate", () => {
  it("reads a date-only value as a local calendar day", () => {
    expect(localDate("2026-09-01")).toBe(new Date(2026, 8, 1).toLocaleDateString());
  });

  it("shows a known posting date plainly", () => {
    render(<PostedDate row={row({ posted_at: "2026-09-01", posted_known: true })} />);
    expect(screen.getByText(localDate("2026-09-01")).getAttribute("title")).toBeNull();
  });

  it("marks the date found when the posting date is unknown", () => {
    render(<PostedDate row={row({ posted_at: "2026-09-20", posted_known: false })} />);
    const cell = screen.getByText(`~${localDate("2026-09-20")}`);
    expect(cell.getAttribute("title")).toBe("Posting date unknown — date found");
  });
});
