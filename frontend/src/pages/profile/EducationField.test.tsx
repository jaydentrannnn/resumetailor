// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplicantProfile, ProfileOptions } from "../../api";
import type { FieldContext } from "./fieldContext";
import { EducationField } from "./EducationField";

const state = vi.hoisted(() => ({ options: null as ProfileOptions | null }));
vi.mock("../../lib/profileOptions", () => ({ useProfileOptions: () => state.options }));
afterEach(() => {
  cleanup();
  state.options = null;
});

function context(value = ""): FieldContext {
  return {
    draft: { highest_education_obtained: value } as ApplicantProfile,
    set: vi.fn(),
    setMany: vi.fn(),
    touch: vi.fn(),
    errors: {},
    gapFields: new Set(),
    defaults: {},
    fallbacks: {},
    passwordSet: false,
  };
}

function options() {
  state.options = {
    education_levels: ["High school diploma", "Bachelor's degree"],
    education_level_aliases: { bachelors: "Bachelor's degree" },
  } as ProfileOptions;
}

describe("completed education picker", () => {
  it("offers standard choices, saves a selection, and reloads it", () => {
    options();
    const ctx = context();
    const { rerender } = render(<EducationField ctx={ctx} />);
    const select = screen.getByLabelText("Highest education completed") as HTMLSelectElement;
    expect(select.value).toBe("");
    expect(screen.queryByText("Decline to answer")).toBeNull();
    fireEvent.change(select, { target: { value: "High school diploma" } });
    expect(ctx.set).toHaveBeenCalledWith("highest_education_obtained", "High school diploma");
    rerender(<EducationField ctx={context("High school diploma")} />);
    expect(select.value).toBe("High school diploma");
    fireEvent.change(select, { target: { value: "" } });
    expect(select.value).toBe("High school diploma"); // controlled until the draft updates
  });

  it("preserves a legacy alias when choices arrive without rewriting the draft", () => {
    const ctx = context("Bachelors");
    const { rerender } = render(<EducationField ctx={ctx} />);
    options();
    rerender(<EducationField ctx={ctx} />);
    expect((screen.getByLabelText("Highest education completed") as HTMLSelectElement).value).toBe(
      "Bachelor's degree",
    );
    expect(screen.queryByLabelText("Highest education completed, other")).toBeNull();
    expect(ctx.set).not.toHaveBeenCalled();
    expect(ctx.draft.highest_education_obtained).toBe("Bachelors");
  });

  it("preserves custom text under Other and accepts another custom qualification", () => {
    options();
    const ctx = context("Higher National Diploma");
    render(<EducationField ctx={ctx} />);
    const input = screen.getByLabelText("Highest education completed, other") as HTMLInputElement;
    expect(input.value).toBe("Higher National Diploma");
    fireEvent.change(input, { target: { value: "Diploma in Engineering" } });
    expect(ctx.set).toHaveBeenCalledWith("highest_education_obtained", "Diploma in Engineering");
  });

  it("opens Other without saving a sentinel and can clear the selection", () => {
    options();
    const ctx = context();
    const { rerender } = render(<EducationField ctx={ctx} />);
    fireEvent.change(screen.getByLabelText("Highest education completed"), {
      target: { value: "__other__" },
    });
    expect(ctx.set).toHaveBeenCalledWith("highest_education_obtained", "");
    expect(screen.getByLabelText("Highest education completed, other")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Highest education completed"), {
      target: { value: "" },
    });
    rerender(<EducationField ctx={context()} />);
    expect(screen.queryByLabelText("Highest education completed, other")).toBeNull();
  });
});
