// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TargetFieldSection } from "./TargetFieldSection";

const { state, save } = vi.hoisted(() => ({
  save: vi.fn(),
  state: {
    config: {
      target_field: null as string | null,
      target_field_summary: "Existing profile guidance.",
      target_fields: [
        { id: "general", label: "General", summary: "General evidence" },
        { id: "finance-consulting", label: "Finance & Consulting", summary: "Analysis" },
      ],
      effective_vocabulary_packs: ["core-tech"],
    },
    settings: { rewrite_style: "Keep my style", expand_style: null, cover_style: null },
    settingsLoaded: true,
  },
}));

vi.mock("../../state/runState", () => ({
  useRunState: () => ({ ...state, setTargetField: save }),
}));

afterEach(cleanup);
beforeEach(() => {
  state.config.target_field = null;
  save.mockReset();
});

it("saves one profile field and keeps custom writing styles visible", async () => {
  save.mockResolvedValue(undefined);
  render(<TargetFieldSection />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "finance-consulting" } });
  await waitFor(() => expect(save).toHaveBeenCalledWith("finance-consulting"));
  expect(screen.getByText("Custom style")).toBeTruthy();
  expect(state.settings.rewrite_style).toBe("Keep my style");
});

it("reports a failed save and continues showing the saved field", async () => {
  state.config.target_field = "general";
  save.mockRejectedValue(new Error("Could not save field"));
  render(<TargetFieldSection />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "finance-consulting" } });
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not save field");
  expect(screen.getByRole("combobox")).toHaveProperty("value", "general");
});

it("allows returning an opted-in profile to its existing guidance", async () => {
  state.config.target_field = "finance-consulting";
  save.mockResolvedValue(undefined);
  render(<TargetFieldSection />);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
  await waitFor(() => expect(save).toHaveBeenCalledWith(null));
});
