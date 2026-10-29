import { expect, it } from "vitest";
import { contactErrors, realContact } from "./onboardingContact";
import { personalComplete, openGaps } from "./onboarding";
import type { MasterResume } from "./resumeEdit";

it("rejects malformed resume contact and placeholders even through fallbacks", () => {
  expect(
    contactErrors({ name: "Test", email: "bad", phone: "abc" } as MasterResume["contact"]),
  ).toHaveProperty("email");
  expect(
    contactErrors({ name: "Test", email: "bad", phone: "abc" } as MasterResume["contact"]),
  ).toHaveProperty("phone");
  expect(realContact("Your Name")).toBe("");
  expect(
    personalComplete({ first_name: "", last_name: "", email: "", phone: "" }, {}, null, {
      first_name: "Your",
      last_name: "Name",
      email: "you@example.com",
      phone: "5550100",
    }),
  ).toBe(false);
});

it("reads nested voluntary answers and accepts No as answered", () => {
  expect(
    openGaps(["gender", "hispanic_latino", "veteran_status", "disability_status"], {
      eeo: { gender: "decline", hispanic_latino: false, veteran: "decline", disability: "No" },
    }),
  ).toEqual([]);
});
