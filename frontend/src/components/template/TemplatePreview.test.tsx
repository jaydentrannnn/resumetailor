// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TemplatePreview } from "./TemplatePreview";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("hides the old PDF during switching and ignores a late preview response", async () => {
  let completeOld!: (value: Response) => void;
  const oldRequest = new Promise<Response>((resolve) => {
    completeOld = resolve;
  });
  const fetch = vi
    .fn()
    .mockReturnValueOnce(oldRequest)
    .mockResolvedValueOnce({ ok: true, blob: async () => new Blob(["B"]) });
  vi.stubGlobal("fetch", fetch);
  const makeUrl = vi.fn(() => "blob:template-b");
  const realUrl = URL;
  class PreviewURL extends realUrl {
    static createObjectURL = makeUrl;
    static revokeObjectURL = vi.fn();
  }
  vi.stubGlobal("URL", PreviewURL);
  const { rerender } = render(
    <TemplatePreview revision={"a".repeat(64)} pending={null} refreshKey={0} />,
  );
  rerender(<TemplatePreview revision={"a".repeat(64)} pending="B" refreshKey={0} />);
  expect(screen.getByRole("status").textContent).toContain("Switching to B");
  expect(screen.queryByTitle("Template preview")).toBeNull();
  rerender(<TemplatePreview revision={"b".repeat(64)} pending={null} refreshKey={1} />);
  await waitFor(() =>
    expect(screen.getByTitle("Template preview").getAttribute("src")).toContain("blob:template-b"),
  );
  await act(async () => completeOld({ ok: true, blob: async () => new Blob(["A"]) } as Response));
  expect(makeUrl).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[1][0]).toContain(`revision=${"b".repeat(64)}`);
});
