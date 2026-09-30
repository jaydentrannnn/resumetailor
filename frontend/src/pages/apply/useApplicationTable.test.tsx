// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useApplicationTable } from "./useApplicationTable";
import { listApplications } from "../../api";

vi.mock("../../api", () => ({ listApplications: vi.fn(() => Promise.resolve({ applications: [], counts: {}, total: 0 })) }));

describe("useApplicationTable", () => {
  it("defaults the review scope to latest status first", async () => {
    renderHook(() => useApplicationTable("review", "workspace", new URLSearchParams(), vi.fn(), true));
    await waitFor(() => expect(listApplications).toHaveBeenCalled());
    expect(listApplications).toHaveBeenCalledWith(expect.objectContaining({ sort: "status_at", direction: "desc" }));
  });
});
