// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileGapBanner } from "./ProfileGapBanner";
import { MissingProfileFields } from "./MissingProfileFields";
import { ProfileGapsNotice } from "../pages/ApplicationsDashboard";

// No `test.globals`, so Testing Library's automatic cleanup never registers.
afterEach(() => cleanup());

const work = {
  key: "authorized_to_work",
  label: "Authorized to work",
  section: "Work authorization and sponsorship",
  path: "/profile/application",
  seen_in: 2,
};
const notice = {
  key: "notice_period",
  label: "Notice period",
  section: "Availability and location preferences",
  path: "/profile/application",
  seen_in: 0,
};

describe("ProfileGapBanner", () => {
  it("renders nothing without gaps", () => {
    const { container } = render(<ProfileGapBanner gaps={[]} onOpen={vi.fn()} />);
    expect(container.innerHTML).toBe("");
  });

  it("names each blank field with how often fills met it, and opens its section", () => {
    const onOpen = vi.fn();
    render(<ProfileGapBanner gaps={[work, notice]} onOpen={onOpen} />);
    expect(screen.getByText(/met in 2 applications/)).toBeTruthy();
    fireEvent.click(screen.getByText("Authorized to work"));
    expect(onOpen).toHaveBeenCalledWith("Work authorization and sponsorship");
  });
});

describe("MissingProfileFields", () => {
  it("links each blank fact to the profile and says whether it was answered anyway", () => {
    render(
      <MemoryRouter>
        <MissingProfileFields
          items={[
            {
              key: "authorized_to_work",
              field_label: "Authorized to work",
              section: "Work authorization and sponsorship",
              path: "/profile/application",
              questions: ["Are you legally authorized to work in the US?"],
              answered: false,
            },
            {
              key: "notice_period",
              field_label: "Notice period",
              section: "Availability and location preferences",
              path: "/profile/application",
              questions: ["Notice period"],
              answered: true,
            },
          ]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Authorized to work" }).getAttribute("href")).toBe(
      "/profile/application",
    );
    expect(
      screen.getByText(/“Are you legally authorized to work in the US\?” · left blank/),
    ).toBeTruthy();
    expect(screen.getByText(/answered by the Autofill model this time/)).toBeTruthy();
  });
});

describe("ProfileGapsNotice", () => {
  it("summarises the first few gaps on one line", () => {
    const gaps = ["A", "B", "C", "D", "E"].map((label, index) => ({
      ...notice,
      key: `k${index}`,
      label,
    }));
    render(
      <MemoryRouter>
        <ProfileGapsNotice gaps={gaps} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("status").textContent).toContain("A, B, C, D and 1 more");
  });
});
