// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { CoverageFunnel } from "../../api";
import { CoverageBreakdown } from "./CoverageBreakdown";

afterEach(cleanup);

const funnel: CoverageFunnel = {
  total: 5,
  in_resume: 4,
  on_page: 1,
  keywords: [
    { canonical: "python", phrase: "Python", resume: "stated", page: "expressed" },
    { canonical: "tableau", phrase: "Tableau", resume: "stated", page: "tag_only" },
    { canonical: "kubernetes", phrase: "Kubernetes", resume: "inferred", page: "inferred_only" },
    { canonical: "sql", phrase: "SQL", resume: "stated", page: "not_selected" },
    { canonical: "teamwork", phrase: "teamwork", resume: "tagged", page: "demonstrated" },
    { canonical: "go", phrase: "Go", resume: null, page: null },
  ],
  unsupported_additions: [
    ["b1", "docker"],
    ["b2", "docker"],
  ],
};

it("names where each unexpressed skill stopped, and additions once each", () => {
  render(<CoverageBreakdown funnel={funnel} />);
  expect(
    screen.getByText("In your resume, not on the tailored page").nextSibling?.textContent,
  ).toBe("SQL");
  expect(
    screen.getByText("Backed on the tailored page, never named").nextSibling?.textContent,
  ).toBe("Tableau");
  expect(screen.getByText("Only inferred on the tailored page").nextSibling?.textContent).toBe(
    "Kubernetes",
  );
  expect(screen.getByText("Soft skills shown by the work").nextSibling?.textContent).toBe(
    "teamwork",
  );
  expect(screen.getByText("Potentially unsupported additions").nextSibling?.textContent).toBe(
    "docker",
  );
});

it("renders nothing for an old run or a page that names every skill", () => {
  const { container } = render(<CoverageBreakdown funnel={null} />);
  expect(container.innerHTML).toBe("");
  const clean = { ...funnel, keywords: funnel.keywords.slice(0, 1), unsupported_additions: [] };
  expect(render(<CoverageBreakdown funnel={clean} />).container.innerHTML).toBe("");
});
