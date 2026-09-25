import { describe, expect, it } from "vitest";
import type { ApplicationRow, ApplyOperation } from "../api";
import {
  autoSubmitCapLabel,
  fillBlockers,
  formatEta,
  operationEtaSeconds,
  operationHeadline,
  resolveApplyTab,
  reviewReason,
} from "./applyPage";

const row = (patch: Partial<ApplicationRow>): ApplicationRow => ({
  source_job_id: "x",
  company: "Acme",
  role: "Analyst",
  location: "",
  posting_url: "",
  final_url: "",
  ats: "workday",
  status: "awaiting_review",
  discovered_at: "",
  job_id: null,
  screen: null,
  error: null,
  notes: "",
  sources: [],
  group_size: 1,
  salary: "",
  eligibility_flags: [],
  duplicate_of: null,
  ...patch,
});

const op = (patch: Partial<ApplyOperation>): ApplyOperation =>
  ({
    operation_id: "o",
    action: "prepare",
    state: "running",
    application_ids: [],
    current_application_id: "",
    current_label: "Acme",
    stage: "",
    message: "",
    processed: 2,
    total: 12,
    completed: 0,
    blocked: 0,
    failed: 0,
    submitted: 0,
    started_at: "2026-01-01T00:00:00Z",
    updated_at: "",
    heartbeat_at: "",
    current_step: 0,
    application_started_at: "",
    finished_at: "",
    effective_model: "",
    auto_submit: false,
    blocker_mode: "continue",
    events: [],
    ...patch,
  }) as ApplyOperation;

describe("resolveApplyTab", () => {
  it("honours the URL, else prefers Needs you when anything waits", () => {
    expect(resolveApplyTab("done", 3)).toBe("done");
    expect(resolveApplyTab(null, 2)).toBe("needs");
    expect(resolveApplyTab("bogus", 0)).toBe("progress");
    expect(resolveApplyTab(null, null)).toBe("progress");
  });
});

describe("reviewReason", () => {
  it("names the specific next step", () => {
    expect(reviewReason(row({ status: "awaiting_otp" })).action).toBe("Enter code");
    expect(reviewReason(row({ review_summary: "Sign-in needed", ats: "workday" }))).toMatchObject({
      why: "Sign in to Workday",
      action: "Sign in",
    });
    expect(
      reviewReason(row({ fill: { handoff_reason: "reCAPTCHA challenge shown" } })).action,
    ).toBe("CAPTCHA");
    expect(reviewReason(row({ review_summary: "Salary expectations +2" }))).toEqual({
      why: '3 questions left blank, starting with "Salary expectations"',
      action: "Answer 3",
    });
    expect(reviewReason(row({ review_summary: "Ready to submit" })).action).toBe("Final check");
    expect(reviewReason(row({ review_summary: "Check the form" })).action).toBe("Review");
  });

  it("links a blank profile fact to its field", () => {
    const reason = reviewReason(
      row({
        fill: {
          missing_profile: [
            {
              key: "gpa",
              field_label: "GPA",
              section: "Education",
              path: "/profile/application#gpa",
              questions: ["GPA?"],
              answered: false,
            },
          ],
        },
      }),
    );
    expect(reason).toMatchObject({ action: "Profile", profilePath: "/profile/application#gpa" });
  });
});

describe("fillBlockers", () => {
  it("explains why selected rows can't be filled", () => {
    expect(fillBlockers([row({ status: "ready" })])).toBeNull();
    expect(fillBlockers([row({ status: "discovered" }), row({ status: "tailoring" })])).toBe(
      "2 selected can't be filled yet: not tailored",
    );
    expect(fillBlockers([row({ status: "discovered" }), row({ status: "skipped" })])).toBe(
      "2 selected can't be filled yet: 1 not tailored, 1 already finished",
    );
  });
});

describe("operation banner", () => {
  it("reads as a plain phase", () => {
    expect(operationHeadline(op({}))).toBe("Tailoring 3 of 12 · Acme");
    expect(operationHeadline(op({ state: "paused" }))).toBe("Paused · tailoring");
    expect(operationHeadline(op({ state: "completed", action: "fill" }))).toBe("Filling completed");
  });

  it("estimates the remaining time from items done", () => {
    const now = Date.parse("2026-01-01T00:04:00Z");
    expect(operationEtaSeconds(op({}), now)).toBe(1200);
    expect(operationEtaSeconds(op({ processed: 0 }), now)).toBeNull();
    expect(formatEta(1200)).toBe("about 20 min");
    expect(formatEta(20)).toBe("under a minute");
  });

  it("never lets a cap of 0 read as unlimited", () => {
    expect(autoSubmitCapLabel(0)).toBe("No auto-submits");
    expect(autoSubmitCapLabel(5)).toBe("At most 5 per run");
  });
});
