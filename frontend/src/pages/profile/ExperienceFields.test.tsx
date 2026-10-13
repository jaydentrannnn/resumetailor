// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getApplicantProfile,
  putApplicantProfile,
  type ApplicantProfile,
  type ApplicantProfileResponse,
  type ExperienceSummary,
} from "../../api";
import { emitAppEvent } from "../../lib/appEvents";
import { ApplicantProfileProvider, useApplicantProfile } from "../../state/applicantProfileState";
import { ExperienceFields } from "./ExperienceFields";
import type { FieldContext } from "./fieldContext";

vi.mock("../../api", async (original) => ({
  ...(await original<typeof import("../../api")>()),
  getApplicantProfile: vi.fn(),
  putApplicantProfile: vi.fn(),
}));

function summary(
  years: number | null,
  excluded: ExperienceSummary["excluded_entries"] = [],
): ExperienceSummary {
  return { years, as_of: "2026-10-12", excluded_entries: excluded };
}

function response(years: number | null = 1.234567): ApplicantProfileResponse {
  return {
    profile: {
      experience_basis: "experience",
      experience_years_custom: null,
      city: "Saved City",
    } as ApplicantProfile,
    workspace_id: "test",
    seeded: true,
    workday_password_set: false,
    experience_summaries: {
      experience: summary(years, [
        { label: "Undated role", kind: "experience", reason: "Missing start date" },
      ]),
      experience_projects: summary(2.5),
      experience_projects_education: summary(4.75),
    },
  };
}

function Fields() {
  const state = useApplicantProfile();
  if (!state.draft) return null;
  const ctx: FieldContext = {
    draft: state.draft,
    set: (key, value) => state.setDraft({ ...state.draft!, [key]: value }),
    setMany: (patch) => state.setDraft({ ...state.draft!, ...patch }),
    errors: {},
    gapFields: new Set(),
    defaults: {},
    fallbacks: {},
    passwordSet: false,
    touch: () => undefined,
  };
  return (
    <>
      <ExperienceFields ctx={ctx} />
      <input
        aria-label="Pending profile city"
        value={state.draft.city}
        onChange={(event) => state.setDraft({ ...state.draft!, city: event.target.value })}
      />
      <output data-testid="experience-state">
        {JSON.stringify({
          saved: state.saved,
          draft: state.draft,
          summaries: state.experienceSummaries,
        })}
      </output>
    </>
  );
}

function mount() {
  return render(
    <ApplicantProfileProvider>
      <Fields />
    </ApplicantProfileProvider>,
  );
}

function state() {
  return JSON.parse(screen.getByTestId("experience-state").textContent || "{}");
}

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getApplicantProfile).mockResolvedValue(response());
});

describe("experience source preference", () => {
  it("displays a dated subtotal with excluded evidence and retains the unrounded server value", async () => {
    mount();
    expect(await screen.findByText("1.23 years from dated entries")).toBeTruthy();
    expect(screen.getByText("Undated role: Missing start date")).toBeTruthy();
    expect(state().summaries.experience.years).toBe(1.234567);
    expect(screen.getByText(/Used for general and professional experience questions/)).toBeTruthy();
    expect(putApplicantProfile).not.toHaveBeenCalled();
  });

  it("offers the four bases and switches the displayed calculation with the profile draft", async () => {
    mount();
    const select = (await screen.findByLabelText("Years of experience from")) as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.text)).toEqual([
      "Experience",
      "Experience and projects",
      "Experience, projects, and education",
      "Custom years",
    ]);
    fireEvent.change(select, { target: { value: "experience_projects" } });
    expect(screen.getByText("2.50 years from dated entries")).toBeTruthy();
    expect(screen.queryByText("Undated role: Missing start date")).toBeNull();
    expect(state().draft.experience_basis).toBe("experience_projects");
    fireEvent.change(select, { target: { value: "experience_projects_education" } });
    expect(screen.getByText("4.75 years from dated entries")).toBeTruthy();
    expect(state().saved.experience_basis).toBe("experience");
  });

  it("accepts fractional custom years, preserves them across source switches, and clears to null", async () => {
    mount();
    const select = await screen.findByLabelText("Years of experience from");
    fireEvent.change(select, { target: { value: "custom" } });
    const input = screen.getByLabelText("Custom years of experience") as HTMLInputElement;
    expect(input.min).toBe("0");
    expect(input.step).toBe("any");
    fireEvent.change(input, { target: { value: "1.5" } });
    expect(state().draft.experience_years_custom).toBe(1.5);
    fireEvent.change(select, { target: { value: "experience" } });
    expect(screen.queryByLabelText("Custom years of experience")).toBeNull();
    fireEvent.change(select, { target: { value: "custom" } });
    expect((screen.getByLabelText("Custom years of experience") as HTMLInputElement).value).toBe(
      "1.5",
    );
    fireEvent.change(screen.getByLabelText("Custom years of experience"), {
      target: { value: "" },
    });
    expect(state().draft.experience_years_custom).toBeNull();
  });

  it.each([
    [null, "No dated subtotal available"],
    [0, "0.00 years from dated entries"],
  ] as const)("distinguishes %s years from a missing subtotal", async (years, label) => {
    vi.mocked(getApplicantProfile).mockResolvedValue(response(years));
    mount();
    expect(await screen.findByText(label)).toBeTruthy();
  });

  it("refreshes summaries after a resume save without discarding a pending profile draft", async () => {
    mount();
    await screen.findByText("1.23 years from dated entries");
    await waitFor(() => expect(getApplicantProfile).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByLabelText("Pending profile city"), {
      target: { value: "Unsaved City" },
    });
    vi.mocked(getApplicantProfile).mockResolvedValue(response(3.5));
    await act(async () => emitAppEvent("rt:resume-saved"));
    expect(await screen.findByText("3.50 years from dated entries")).toBeTruthy();
    expect(state().draft.city).toBe("Unsaved City");
    expect(state().saved.city).toBe("Saved City");
    expect(putApplicantProfile).not.toHaveBeenCalled();
  });
});
