// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Education } from "../../lib/resumeEdit";
import { EducationDegreeFields } from "./EducationDegreeFields";

vi.mock("../../lib/profileOptions", () => ({
  useProfileOptions: () => ({
    degree_types: ["B.S.", "B.A.", "Bachelor of Science"],
    fields_of_study: ["Computer Science", "Data Science", "Management"],
  }),
}));

afterEach(() => cleanup());

function education(patch: Partial<Education> = {}): Education {
  return {
    school: "Synthetic University",
    dates: "Expected June 2027",
    degree: "B.S. in Computer Science; Minor in Management",
    degree_type: "B.S.",
    degree_mode: "generated",
    degree_format: "semicolon",
    majors: ["Computer Science"],
    major_entries: [{ name: "Computer Science", degree_type: "B.S." }],
    minors: ["Management"],
    ...patch,
  };
}

function Harness({ initial = education() }: { initial?: Education }) {
  const [edu, setEdu] = useState(initial);
  return (
    <>
      <EducationDegreeFields edu={edu} onChange={setEdu} />
      <output data-testid="education-state">{JSON.stringify(edu)}</output>
    </>
  );
}

function saved(): Education {
  return JSON.parse(screen.getByTestId("education-state").textContent || "{}");
}

describe("education degree editor", () => {
  it("shows a generated line with exactly one compact separator selected", () => {
    render(<Harness />);
    expect(screen.getByText("B.S. in Computer Science; Minor in Management")).toBeTruthy();
    const group = screen.getByRole("group", { name: "Degree separator" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([";", ",", "|"]);
    expect(
      within(group).getByRole("button", { name: "Semicolon" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(within(group).getByRole("button", { name: "Comma" }));
    expect(buttons.filter((button) => button.getAttribute("aria-pressed") === "true")).toHaveLength(
      1,
    );
    expect(screen.getByText("B.S. in Computer Science, Minor in Management")).toBeTruthy();
    fireEvent.click(within(group).getByRole("button", { name: "Vertical bar" }));
    expect(buttons.filter((button) => button.getAttribute("aria-pressed") === "true")).toHaveLength(
      1,
    );
    expect(within(group).getByRole("button", { name: "Comma" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
    expect(saved().degree_format).toBe("pipe");
    expect(screen.getByText("B.S. in Computer Science | Minor in Management")).toBeTruthy();
  });

  it("adds a major as a row and combines a shared degree while preserving its type choice", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
    fireEvent.click(screen.getByRole("button", { name: "Major", exact: true }));
    fireEvent.change(screen.getByLabelText("Major 2 field of study"), {
      target: { value: "Data Science" },
    });
    expect(
      screen.getByText("B.S. in Computer Science and Data Science; Minor in Management"),
    ).toBeTruthy();
    expect(saved().major_entries).toEqual([
      { name: "Computer Science", degree_type: "B.S." },
      { name: "Data Science", degree_type: "B.S." },
    ]);
    fireEvent.change(screen.getByLabelText("Major 2 degree type"), {
      target: { value: "Bachelor of Science" },
    });
    expect(
      screen.getByText("B.S. in Computer Science and Data Science; Minor in Management"),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Major 2 degree type"), { target: { value: "B.A." } });
    expect(
      screen.getByText("B.S. in Computer Science; B.A. in Data Science; Minor in Management"),
    ).toBeTruthy();
  });

  it("adds and removes minor rows without asking for a minor degree type", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Add entry" }));
    fireEvent.click(screen.getByRole("button", { name: "Minor", exact: true }));
    expect(screen.queryByLabelText("Minor 3 degree type")).toBeNull();
    fireEvent.change(screen.getByLabelText("Minor 3 field of study"), {
      target: { value: "Statistics" },
    });
    expect(
      screen.getByText("B.S. in Computer Science; Minors in Management and Statistics"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Remove minor 2" }));
    expect(saved().minors).toEqual(["Statistics"]);
    expect(screen.getByText("B.S. in Computer Science; Minor in Statistics")).toBeTruthy();
  });

  it("reorders majors and updates which major is first for application fields", () => {
    render(
      <Harness
        initial={education({
          degree: "B.S. in Computer Science and Data Science",
          minors: [],
          majors: ["Computer Science", "Data Science"],
          major_entries: [
            { name: "Computer Science", degree_type: "B.S." },
            { name: "Data Science", degree_type: "B.S." },
          ],
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Move major 2 up" }));
    expect(saved().majors).toEqual(["Data Science", "Computer Science"]);
    expect(screen.getByText("B.S. in Data Science and Computer Science")).toBeTruthy();
    expect((screen.getByLabelText("Major 1 field of study") as HTMLInputElement).value).toBe(
      "Data Science",
    );
  });

  it("preserves manual wording through structured edits and rebuilds only when switched back", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("switch", { name: "Write it myself" }));
    expect(screen.queryByRole("group", { name: "Degree separator" })).toBeNull();
    fireEvent.change(screen.getByLabelText("Degree"), {
      target: { value: "My exact custom wording / Honors" },
    });
    fireEvent.change(screen.getByLabelText("Major 1 field of study"), {
      target: { value: "Data Science" },
    });
    expect(saved().degree).toBe("My exact custom wording / Honors");
    expect(saved().degree_mode).toBe("manual");
    fireEvent.click(screen.getByRole("switch", { name: "Write it myself" }));
    expect(saved().degree_mode).toBe("generated");
    expect(screen.getByText("B.S. in Data Science; Minor in Management")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Degree separator" })).toBeTruthy();
  });

  it("can derive editable rows from a legacy manual line without replacing its wording", () => {
    const degree = "Bachelor of Science in Computer Science; Minor in Management";
    render(
      <Harness
        initial={education({
          degree,
          degree_mode: "manual",
          degree_type: "",
          majors: [],
          major_entries: [],
          minors: [],
        })}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Fill type, majors and minors from this line" }),
    );
    expect(saved().major_entries).toEqual([
      { name: "Computer Science", degree_type: "Bachelor of Science" },
    ]);
    expect(saved().minors).toEqual(["Management"]);
    expect(saved().degree_mode).toBe("manual");
    expect((screen.getByLabelText("Degree") as HTMLInputElement).value).toBe(degree);
  });
});
