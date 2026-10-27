// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getApplicantProfile,
  putApplicantProfile,
  type ApplicantProfile,
  type ApplicantProfileResponse,
} from "../../api";
import { ApplicantProfileProvider, useApplicantProfile } from "../../state/applicantProfileState";
import { AnswerPreferences } from "./AnswerPreferences";

vi.mock("../../api", async (original) => ({
  ...(await original<typeof import("../../api")>()),
  getApplicantProfile: vi.fn(),
  putApplicantProfile: vi.fn(),
}));

function profile(patch: Partial<ApplicantProfile> = {}): ApplicantProfile {
  return {
    first_name: "Synthetic",
    last_name: "Applicant",
    city: "Saved City",
    how_heard: "LinkedIn",
    auto_accept_notices: true,
    auto_accept_agreements: false,
    consider_other_positions: null,
    minimum_qualifications_answer: null,
    ...patch,
  } as ApplicantProfile;
}

function response(value = profile()): ApplicantProfileResponse {
  return { profile: value, workspace_id: "test", seeded: true, workday_password_set: false };
}

function DraftProbe() {
  const state = useApplicantProfile();
  if (!state.draft) return null;
  return (
    <>
      <input
        aria-label="Pending profile city"
        value={state.draft.city}
        onChange={(event) => state.setDraft({ ...state.draft!, city: event.target.value })}
      />
      <output data-testid="profile-state">
        {JSON.stringify({ saved: state.saved, draft: state.draft, dirty: state.dirty })}
      </output>
    </>
  );
}

function mount() {
  return render(
    <MemoryRouter>
      <ApplicantProfileProvider>
        <AnswerPreferences />
        <DraftProbe />
      </ApplicantProfileProvider>
    </MemoryRouter>,
  );
}

function state() {
  return JSON.parse(screen.getByTestId("profile-state").textContent || "{}") as {
    saved: ApplicantProfile;
    draft: ApplicantProfile;
    dirty: boolean;
  };
}

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getApplicantProfile).mockResolvedValue(response());
  vi.mocked(putApplicantProfile).mockImplementation(async (value) => response(value));
});

describe("Apply answering preferences", () => {
  it("keeps unspecified factual/recruiting preferences at Ask me independently of notice consent", async () => {
    mount();
    const qualification = (await screen.findByLabelText(
      "General minimum-qualification questions",
    )) as HTMLSelectElement;
    expect(qualification.value).toBe("");
    expect(
      (screen.getByLabelText("Consider me for other positions") as HTMLSelectElement).value,
    ).toBe("");
    expect(
      (
        screen.getByRole("switch", {
          name: "Agree to required notices",
        }) as HTMLInputElement
      ).checked,
    ).toBe(true);
    expect(
      (
        screen.getByRole("switch", {
          name: "Agree to terms, certifications and signatures",
        }) as HTMLInputElement
      ).checked,
    ).toBe(false);
    expect(screen.getByText("Advertising-partner sharing:").textContent).toContain("No");
    expect(putApplicantProfile).not.toHaveBeenCalled();
  });

  it.each([
    ["General minimum-qualification questions", "minimum_qualifications_answer"],
    ["Consider me for other positions", "consider_other_positions"],
  ] as const)("saves Yes, No and Ask me explicitly for %s", async (label, key) => {
    mount();
    const select = (await screen.findByLabelText(label)) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "yes" } });
    await waitFor(() => expect(state().saved[key]).toBe(true));
    fireEvent.change(select, { target: { value: "no" } });
    await waitFor(() => expect(state().saved[key]).toBe(false));
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => expect(state().saved[key]).toBeNull());
    expect(vi.mocked(putApplicantProfile).mock.calls.map(([value]) => value[key])).toEqual([
      true,
      false,
      null,
    ]);
    expect(state().saved.auto_accept_notices).toBe(true);
  });

  it("saves required-consent preference without implicitly enabling qualification or recruiting answers", async () => {
    mount();
    const consent = await screen.findByRole("switch", {
      name: "Agree to required notices",
    });
    fireEvent.click(consent);
    await waitFor(() => expect(state().saved.auto_accept_notices).toBe(false));
    expect(state().saved.minimum_qualifications_answer).toBeNull();
    expect(state().saved.consider_other_positions).toBeNull();
    expect(putApplicantProfile).toHaveBeenCalledWith(
      expect.objectContaining({ auto_accept_notices: false }),
    );
  });

  it("agrees to terms and signatures only when switched on", async () => {
    mount();
    const agreements = await screen.findByRole("switch", {
      name: "Agree to terms, certifications and signatures",
    });
    fireEvent.click(agreements);
    await waitFor(() => expect(state().saved.auto_accept_agreements).toBe(true));
    expect(state().saved.auto_accept_notices).toBe(true);
  });

  it("preserves a pending profile draft while saving consecutive Apply preferences", async () => {
    mount();
    const draftCity = await screen.findByLabelText("Pending profile city");
    fireEvent.change(draftCity, { target: { value: "Unsaved City" } });
    fireEvent.change(screen.getByLabelText("General minimum-qualification questions"), {
      target: { value: "yes" },
    });
    await waitFor(() => expect(state().saved.minimum_qualifications_answer).toBe(true));
    expect(state().saved.city).toBe("Saved City");
    expect(state().draft.city).toBe("Unsaved City");
    expect(state().draft.minimum_qualifications_answer).toBe(true);
    expect(state().dirty).toBe(true);
    fireEvent.change(screen.getByLabelText("Consider me for other positions"), {
      target: { value: "no" },
    });
    await waitFor(() => expect(state().saved.consider_other_positions).toBe(false));
    expect(state().draft.city).toBe("Unsaved City");
    expect(state().draft.consider_other_positions).toBe(false);
    expect(state().draft.minimum_qualifications_answer).toBe(true);
    expect(
      vi.mocked(putApplicantProfile).mock.calls.every(([value]) => value.city === "Saved City"),
    ).toBe(true);
  });

  it("reports a failed save while preserving saved answers and the unsaved profile draft", async () => {
    vi.mocked(putApplicantProfile).mockRejectedValueOnce(new Error("Could not save preferences"));
    mount();
    fireEvent.change(await screen.findByLabelText("Pending profile city"), {
      target: { value: "Unsaved City" },
    });
    fireEvent.change(screen.getByLabelText("Consider me for other positions"), {
      target: { value: "yes" },
    });
    expect((await screen.findByRole("alert")).textContent).toContain("Could not save preferences");
    expect(state().saved.consider_other_positions).toBeNull();
    expect(state().draft.city).toBe("Unsaved City");
    expect(state().dirty).toBe(true);
  });

  it("disables preference controls until the save completes", async () => {
    let resolve!: (value: ApplicantProfileResponse) => void;
    vi.mocked(putApplicantProfile).mockReturnValueOnce(
      new Promise((done) => {
        resolve = done;
      }),
    );
    mount();
    const select = await screen.findByLabelText("Consider me for other positions");
    fireEvent.change(select, { target: { value: "yes" } });
    expect((select.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
    await act(async () => resolve(response(profile({ consider_other_positions: true }))));
    expect((select.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(false);
    expect(state().saved.consider_other_positions).toBe(true);
  });
});
