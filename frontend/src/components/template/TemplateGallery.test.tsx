// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { TemplateThumb } from "./TemplateGallery";

afterEach(cleanup);

it("opens the full page and restores focus to the thumbnail on Escape", () => {
  render(<TemplateThumb src="/compact.png" alt="First page of Compact" label="Compact" />);
  const trigger = screen.getByRole("button", { name: "Zoom Compact" });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "Compact" });
  expect(
    within(dialog).getByRole("img", { name: "First page of Compact" }).getAttribute("src"),
  ).toBe("/compact.png");
  expect(document.activeElement).toBe(dialog);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it("disables zoom when the thumbnail cannot load", () => {
  render(<TemplateThumb src="/missing.png" alt="First page of Missing" label="Missing" />);
  fireEvent.error(screen.getByRole("img"));
  expect(screen.getByRole("button", { name: "Zoom Missing" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByText("Preview unavailable (needs Word or LibreOffice)")).toBeTruthy();
});
