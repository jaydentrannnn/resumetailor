// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { TemplateWorkspace } from "./TemplateWorkspace";

vi.mock("./ResumeView", () => ({ ResumeView: () => <p>resume tools</p> }));
vi.mock("./CoverLetterView", () => ({ CoverLetterView: () => <p>letter tools</p> }));
const template = vi.hoisted(() => ({
  info: { tagged: { exists: true } } as { tagged: { exists: boolean } } | null,
  loading: false,
  previewRevision: "r1",
}));
vi.mock("../../../state/templateState", () => ({ useTemplateState: () => template }));

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

afterEach(() => {
  cleanup();
  template.info = { tagged: { exists: true } };
});

it("switches views and keeps the view in the URL", () => {
  render(
    <MemoryRouter initialEntries={["/template"]}>
      <TemplateWorkspace />
      <Where />
    </MemoryRouter>,
  );
  expect(screen.getByText("resume tools")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Cover letter" }));
  expect(screen.getByText("letter tools")).toBeTruthy();
  expect(screen.queryByText("resume tools")).toBeNull();
  expect(screen.getByTestId("where").textContent).toBe("?view=cover");
  fireEvent.click(screen.getByRole("tab", { name: "Resume" }));
  expect(screen.getByTestId("where").textContent).toBe("");
});

it("opens on the cover letter from a link, and has no views without a template", () => {
  const { unmount } = render(
    <MemoryRouter initialEntries={["/template?view=cover"]}>
      <TemplateWorkspace />
    </MemoryRouter>,
  );
  expect(screen.getByText("letter tools")).toBeTruthy();
  unmount();
  template.info = { tagged: { exists: false } };
  render(
    <MemoryRouter>
      <TemplateWorkspace />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("tablist")).toBeNull();
  expect(screen.getByText(/No template yet/)).toBeTruthy();
});
