import { describe, expect, it } from "vitest";
import type { ApplicationRow, ApplyOperation, JobStatus } from "../api";
import {
  ageChoice,
  autoSubmitCapLabel,
  autoSubmitSummary,
  nightlyRunLabel,
  fillBlockers,
  findProgress,
  itemProgress,
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

describe("Find jobs progress", () => {
  const search = (patch: Partial<ApplyOperation> = {}) => op({ action: "find", ...patch });
  it("uses measured source and posting counts for the two halves", () => {
    const sources = search({
      find_progress: { phase: "discovering", processed: 2, total: 4, current: "Internships" },
    });
    expect(findProgress(sources)).toEqual({
      fraction: 0.25,
      detail: "Fetching sources: 2 of 4 · Internships",
    });
    const postings = search({
      find_progress: { phase: "processing", processed: 8, total: 20, current: "Acme" },
    });
    expect(findProgress(postings)?.fraction).toBe(0.7);
    expect(findProgress(postings)?.detail).toBe("Processing postings: 8 of 20 · Acme");
    expect(operationHeadline(sources)).toBe("Finding jobs");
    expect(operationEtaSeconds(postings, Date.now())).toBeNull();
  });
  it("skips empty stages and reserves 100% for completion", () => {
    const finding = search({
      find_progress: { phase: "discovering", processed: 0, total: 0, current: "" },
    });
    expect(findProgress(finding)?.fraction).toBe(0.5);
    finding.find_progress!.phase = "processing";
    expect(findProgress(finding)?.fraction).toBe(0.99);
    for (const state of ["completed", "completed_with_issues"])
      expect(findProgress({ ...finding, state })?.fraction).toBe(1);
  });
  it("retains measured progress on failure, cancellation and interruption", () => {
    for (const state of ["failed", "cancelled", "interrupted"])
      expect(
        findProgress(
          search({
            state,
            find_progress: { phase: "processing", processed: 1, total: 2, current: "" },
          }),
        )?.fraction,
      ).toBe(0.75);
  });
  it("supports old operations and leaves Prepare and Fill alone", () => {
    expect(findProgress(search())).toBeNull();
    expect(findProgress(search({ state: "completed" }))?.fraction).toBe(1);
    expect(findProgress(op({}))).toBeNull();
    expect(findProgress(op({ action: "fill" }))).toBeNull();
  });
});

describe("resolveApplyTab", () => {
  it("honours the URL, else prefers Needs you when anything waits", () => {
    expect(resolveApplyTab("done", 3)).toBe("done");
    expect(resolveApplyTab("sources", 3)).toBe("needs");
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

describe("autoSubmitSummary", () => {
  const caps = {
    auto_submit_enabled: true,
    auto_submit_max_per_run: 5,
    auto_submit_max_per_day: 25,
    auto_submit_max_per_company_per_day: 2,
  };
  it("reads the three caps as one sentence", () => {
    expect(autoSubmitSummary(caps)).toBe(
      "Nightly run: up to 5 · no more than 25 a day · no more than 2 per company.",
    );
    expect(autoSubmitSummary({ ...caps, auto_submit_max_per_run: 0 })).toContain(
      "Nightly run: none",
    );
  });
  it("says when nothing is submitted", () => {
    expect(autoSubmitSummary({ ...caps, auto_submit_enabled: false })).toContain("off");
    expect(autoSubmitSummary({ ...caps, auto_submit_max_per_day: 0 })).toContain(
      "nothing is submitted",
    );
  });
});

describe("nightlyRunLabel", () => {
  it("shows on with the time, or off", () => {
    expect(nightlyRunLabel({ enabled: false, schedule_time: "02:00" })).toBe("Nightly run: off");
    expect(nightlyRunLabel({ enabled: true, schedule_time: "02:00" })).toMatch(
      /^Nightly run: on · 2:00/,
    );
  });
});

describe("itemProgress", () => {
  const now = Date.parse("2026-01-01T00:04:00Z");
  const job = (stages: string[]): JobStatus =>
    ({
      job_id: "job-1",
      status: "running",
      queue_position: null,
      error: null,
      report: null,
      expansion: null,
      skills: null,
      cover_letter: null,
      events: stages.map((stage) => ({ stage, message: stage })),
    }) as JobStatus;

  it("reads a Prepare item's tailor job steps", () => {
    const running = op({ current_application_id: "a", current_job_id: "job-1" });
    const item = itemProgress(
      running,
      job(["start", "extract", "score", "facets", "fit", "rewrite"]),
      now,
    );
    expect(item?.detail).toBe("Tailoring, step 4 of 6 (Rewriting bullets)");
    expect(item?.estimate).toBe(false);
    expect(item!.fraction).toBeGreaterThan(0.3);
    expect(item!.fraction).toBeLessThan(1);
    // Another item's job, or none yet: nothing to show inside the item.
    expect(
      itemProgress(
        op({ current_application_id: "a", current_job_id: "job-2" }),
        job(["extract"]),
        now,
      ),
    ).toBeNull();
    expect(itemProgress(op({ current_application_id: "a" }), null, now)).toBeNull();
  });

  it("estimates a Fill item from form pages, else from time against its deadline", () => {
    const filling = op({ action: "fill", current_application_id: "a" });
    expect(itemProgress({ ...filling, current_step: 3 }, null, now)).toEqual({
      fraction: 3 / 9,
      detail: "Filling, page 3 (estimate)",
      estimate: true,
    });
    expect(itemProgress({ ...filling, current_step: 20 }, null, now)?.fraction).toBe(0.9);
    const timed = itemProgress(
      {
        ...filling,
        application_started_at: "2026-01-01T00:02:00Z",
        application_deadline_at: "2026-01-01T00:06:00Z",
      },
      null,
      now,
    );
    expect(timed?.fraction).toBeCloseTo(0.5);
  });

  it("counts the item in flight toward the time left", () => {
    // 4 minutes for half of the first item: 8 minutes per item, 11.5 items to go.
    expect(operationEtaSeconds(op({ processed: 0 }), now, 0.5)).toBe(5520);
  });
});

describe("ageChoice", () => {
  it("selects the preset segments and treats every other window as custom", () => {
    expect(ageChoice(1)).toBe("1");
    expect(ageChoice(7)).toBe("7");
    expect(ageChoice(3)).toBe("custom");
    expect(ageChoice(0)).toBe("custom");
  });
});
