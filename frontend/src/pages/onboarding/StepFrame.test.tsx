// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConfirmProvider } from "../../state/confirmState";
import { StepFrame, type StepNav } from "./StepFrame";

afterEach(cleanup);

function setup(complete: boolean, onSave = vi.fn(() => Promise.resolve(true))) {
  const nav: StepNav = {
    onBack: vi.fn(),
    onNext: vi.fn(),
    onSkip: vi.fn(),
    saving: false,
    saveRef: { current: () => Promise.resolve(true) },
  };
  render(
    <ConfirmProvider>
      <StepFrame
        title="Step"
        intro="Intro"
        nav={nav}
        complete={complete}
        onSave={onSave}
        skipWarning="Autofill will stop."
      >
        <p>Body</p>
      </StepFrame>
    </ConfirmProvider>,
  );
  return { nav, onSave };
}

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

it("greys out Next until complete, and Skip once complete", () => {
  setup(false);
  expect(button("Next").disabled).toBe(true);
  expect(button("Skip").disabled).toBe(false);
  cleanup();
  setup(true);
  expect(button("Next").disabled).toBe(false);
  expect(button("Skip").disabled).toBe(true);
});

it("saves before going back or forward, and stays when the save fails", async () => {
  const { nav, onSave } = setup(true);
  fireEvent.click(button("Back"));
  await waitFor(() => expect(nav.onBack).toHaveBeenCalled());
  expect(onSave).toHaveBeenCalledTimes(1);
  cleanup();
  const failing = setup(
    true,
    vi.fn(() => Promise.resolve(false)),
  );
  fireEvent.click(button("Next"));
  await waitFor(() => expect(failing.onSave).toHaveBeenCalled());
  expect(failing.nav.onNext).not.toHaveBeenCalled();
});

it("warns before skipping, then saves and skips", async () => {
  const { nav, onSave } = setup(false);
  fireEvent.click(button("Skip"));
  expect(await screen.findByText(/Autofill will stop\./)).toBeTruthy();
  expect(nav.onSkip).not.toHaveBeenCalled();
  const dialog = screen.getByRole("dialog");
  fireEvent.click(
    Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "Skip")!,
  );
  await waitFor(() => expect(nav.onSkip).toHaveBeenCalled());
  expect(onSave).toHaveBeenCalled();
});

it("hands the step's save to the wizard for stepper jumps", () => {
  const { nav, onSave } = setup(true);
  void nav.saveRef.current();
  expect(onSave).toHaveBeenCalled();
});
