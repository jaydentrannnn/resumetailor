import { describe, expect, it } from "vitest";
import type { ApplicantProfile } from "../api";
import {
  PROFILE_GROUPS,
  changedKeys,
  classYearFor,
  groupForField,
  sponsorshipFromVisa,
  tabForField,
  validateProfile,
} from "./profileForm";

const base = {
  first_name: "Alex",
  last_name: "Doe",
  preferred_name: "",
  pronouns: "",
  email: "",
  phone: "",
  phone_country_code: "+1",
  phone_country_region: "",
  address_line1: "",
  address_line2: "",
  city: "",
  state: "",
  postal_code: "",
  country: "United States",
  linkedin_url: "",
  github_url: "",
  portfolio_url: "",
  portfolio_only_when_asked: true,
  work_authorization: "",
  requires_sponsorship_now: null,
  requires_sponsorship_future: null,
  f1_opt_eligible: null,
  earliest_start: "",
  highest_education_obtained: "",
  salary_expectation: "",
  salary_hourly_min: null,
  salary_hourly_max: null,
  salary_yearly_min: null,
  salary_yearly_max: null,
  willing_to_relocate: null,
  location_preference: "",
  over_18: null,
  relatives_at_company: null,
  referred_by: "",
  how_heard: "",
  eeo: { gender: "decline", race: "decline", veteran: "decline", disability: "decline" },
  custom_answers: {},
} satisfies ApplicantProfile;

describe("validateProfile", () => {
  it("accepts blanks and well-formed values", () => {
    expect(validateProfile(base)).toEqual({});
    expect(
      validateProfile({
        ...base,
        email: "alex@example.com",
        phone: "(555) 010-0000",
        linkedin_url: "linkedin.com/in/alex",
        school_email: "alex@school.edu",
        salary_yearly_min: 60000,
        salary_yearly_max: 80000,
        graduation_date: "2027-05",
        hours_per_week_available: 20,
      }),
    ).toEqual({});
  });

  it("flags each malformed field in plain words", () => {
    const errors = validateProfile({
      ...base,
      email: "alex@",
      phone: "12",
      github_url: "not a url",
      school_email: "alex@gmail.com",
      salary_hourly_min: 30,
      salary_hourly_max: 20,
      graduation_date: "May 2027",
      hours_per_week_available: 90,
    });
    expect(Object.keys(errors).sort()).toEqual([
      "email",
      "github_url",
      "graduation_date",
      "hours_per_week_available",
      "phone",
      "salary_hourly_max",
      "school_email",
    ]);
  });
});

describe("helpers", () => {
  it("counts changed fields", () => {
    expect(changedKeys(base, { ...base, city: "Austin", eeo: { ...base.eeo } })).toEqual(["city"]);
  });

  it("mirrors the server's visa rule", () => {
    expect(sponsorshipFromVisa("f1_opt")).toEqual([false, true]);
    expect(sponsorshipFromVisa("h1b")).toEqual([true, true]);
    expect(sponsorshipFromVisa("other")).toBeNull();
  });

  it("knows which tab holds a field", () => {
    expect(tabForField("email")).toBe("personal");
    expect(tabForField("linkedin_url")).toBe("personal");
    expect(tabForField("portfolio_url")).toBe("application");
    expect(tabForField("school_email")).toBe("application");
  });
});

describe("profile groups", () => {
  it("places each field in exactly one group", () => {
    const seen = PROFILE_GROUPS.flatMap((group) => group.fields);
    expect(new Set(seen).size).toBe(seen.length);
    expect(groupForField("visa_status")).toBe("Work authorization and sponsorship");
    expect(groupForField("school_email")).toBe("Education");
    expect(groupForField("first_name")).toBeUndefined();
  });

  it("derives class standing from the graduation month", () => {
    const today = new Date(2026, 5, 15);
    expect(classYearFor("2027-05", today)).toBe("Senior");
    expect(classYearFor("2028-05", today)).toBe("Junior");
    expect(classYearFor("2030-05", today)).toBe("Freshman");
    expect(classYearFor("2026-01", today)).toBeNull();
    expect(classYearFor("", today)).toBeNull();
  });

  it("accepts a phone extension", () => {
    expect(validateProfile({ ...base, phone: "(555) 010-0000 ext. 12" }).phone).toBeUndefined();
  });
});
