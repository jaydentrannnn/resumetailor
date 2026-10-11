// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { setEntryDragImage } from "./entryDragImage";

afterEach(() => {
  document.body.replaceChildren();
});

it("drags an opaque summary-sized card, excludes expanded fields, and cleans up", () => {
  document.body.innerHTML = `<div data-resume-entry>
    <div data-entry-summary><button aria-controls="editor">Example Company</button><p>2024 – Present</p><button id="handle">Drag</button></div>
    <div id="editor"><input value="Unsaved text"></div>
  </div>`;
  const card = document.querySelector<HTMLElement>("[data-resume-entry]")!;
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({
    x: 100,
    y: 200,
    left: 100,
    top: 200,
    width: 480,
    height: 600,
    right: 580,
    bottom: 800,
    toJSON: () => ({}),
  });
  const setDragImage = vi.fn();
  const cleanup = setEntryDragImage(
    document.getElementById("handle")!,
    { setDragImage } as unknown as DataTransfer,
    550,
    220,
  );
  const preview = document.querySelector<HTMLElement>("[data-entry-drag-preview]")!;
  expect(preview.textContent).toContain("Example Company");
  expect(preview.textContent).toContain("2024 – Present");
  expect(preview.querySelector("input")).toBeNull();
  expect(preview.querySelector("[id], [aria-controls]")).toBeNull();
  expect(preview.getAttribute("aria-hidden")).toBe("true");
  expect(preview.inert).toBe(true);
  expect(preview.style.width).toBe("480px");
  expect(setDragImage).toHaveBeenCalledWith(preview, 450, 20);
  cleanup();
  expect(document.querySelector("[data-entry-drag-preview]")).toBeNull();
  expect(document.getElementById("editor")).not.toBeNull();
});
