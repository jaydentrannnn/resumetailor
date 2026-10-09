// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it } from "vitest";
import { Modal } from "./Modal";

afterEach(cleanup);

/** The confirm is rendered *before* the dialog in the tree, as `ConfirmProvider` does. */
function ConfirmOverDialog() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <>
      {confirmOpen && (
        <Modal title="Delete profile" onClose={() => setConfirmOpen(false)}>
          <p>Sure?</p>
        </Modal>
      )}
      <Modal title="Profiles" onClose={() => undefined}>
        <button type="button" onClick={() => setConfirmOpen(true)}>
          Delete
        </button>
      </Modal>
    </>
  );
}

it("stacks a dialog opened later above an earlier one, whatever the tree order", () => {
  render(<ConfirmOverDialog />);
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  const overlays = Array.from(document.body.children).filter((el) =>
    el.querySelector('[role="dialog"]'),
  );
  const titles = overlays.map((el) => el.querySelector("h2")?.textContent);
  // Same z-index, so DOM order decides: the confirm must come last.
  expect(titles).toEqual(["Profiles", "Delete profile"]);
});
