// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sendRunToApply } from "../../api";
import { SendToApply } from "./SendToApply";

vi.mock("../../api", () => ({ sendRunToApply: vi.fn() }));

afterEach(cleanup);

describe("SendToApply (audit #29)", () => {
  it("sends the run with the posting and opens the application", async () => {
    vi.mocked(sendRunToApply).mockResolvedValue({
      application: { source_job_id: "tailor-1", company: "Acme" } as never,
      created: true,
      reasons: [],
    });
    render(
      <MemoryRouter initialEntries={["/tailor"]}>
        <Routes>
          <Route path="/tailor" element={<SendToApply jobId="run1" title="Data Analyst" />} />
          <Route path="/applications/:id" element={<p>Application page</p>} />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Send to Apply" }));
    fireEvent.change(screen.getByLabelText("Link to the posting"), {
      target: { value: "https://jobs.example.com/1" },
    });
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "Acme" } });
    expect(screen.getByLabelText("Role")).toHaveProperty("value", "Data Analyst");
    const dialog = screen.getByRole("dialog");
    fireEvent.submit(dialog.querySelector("form")!);
    expect(await screen.findByText("Application page")).toBeTruthy();
    expect(sendRunToApply).toHaveBeenCalledWith("run1", {
      posting_url: "https://jobs.example.com/1",
      company: "Acme",
      role: "Data Analyst",
    });
  });
});
