// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

type FillReport = {
  filled: Array<{ key: string; value: string; preserved?: boolean }>;
  leftovers: Array<{ label: string; reason?: string }>;
};
const script = readFileSync(
  resolve(process.cwd(), "../src/resume_tailor/apply/forms/filler.js"),
  "utf8",
);
const readinessScript = readFileSync(
  resolve(process.cwd(), "../src/resume_tailor/apply/forms/filler_readiness.js"),
  "utf8",
);

function run(
  fields: Record<string, string>,
  hints: Record<string, string> = {},
  synonyms: string[][] = [
    ["phone", "phone"],
    ["country", "country"],
  ],
): FillReport {
  const filler = window.eval(script) as (input: unknown) => FillReport;
  return filler({ fields, hints, synonyms });
}

beforeEach(() => {
  document.body.innerHTML = "";
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ width: 100, height: 20 }),
  });
});

describe("Apply form filler", () => {
  it("uses +1 for a phone calling code and country text for the address", () => {
    document.body.innerHTML = `
      <fieldset><label for="country">Country</label><select id="country"><option value="">Select</option><option value="us">United States (+1)</option><option value="ca">Canada (+1)</option><option value="gb">United Kingdom (+44)</option></select><input type="tel" name="phone" aria-label="Phone"></fieldset>
      <label for="address-country">Country</label><select id="address-country"><option value="">Select</option><option value="us">United States</option><option value="ca">Canada</option></select>`;
    const ambiguous = run({
      phone_country_code: "+1",
      country: "United States",
      phone: "555 010 0199",
    });
    expect((document.querySelector("#country") as HTMLSelectElement).value).toBe("");
    expect(ambiguous.leftovers.some((item) => item.label === "Country")).toBe(true);
    const resolved = run({
      phone_country_code: "+1",
      phone_country_region: "United States",
      country: "United States",
      phone: "555 010 0199",
    });
    expect((document.querySelector("#country") as HTMLSelectElement).value).toBe("us");
    expect((document.querySelector("#address-country") as HTMLSelectElement).value).toBe("us");
    expect(resolved.filled.some((item) => item.key === "phone_country_code")).toBe(true);
  });

  it("chooses a country identifier only with a matching region and strips a duplicate phone prefix", () => {
    document.body.innerHTML = `<fieldset><label for="code">Calling code</label><select id="code"><option value="">Select</option><option value="US">US</option><option value="CA">CA</option></select><input type="tel" aria-label="Phone"></fieldset>`;
    run({
      phone_country_code: "+1",
      phone_country_region: "United States",
      phone: "+1 555 010 0199",
    });
    expect((document.querySelector("#code") as HTMLSelectElement).value).toBe("US");
    expect((document.querySelector("input") as HTMLInputElement).value).toBe("555 010 0199");
  });

  it("classifies Greenhouse's custom Country control inside the phone group as a calling code", () => {
    document.body.innerHTML = `
      <fieldset class="phone-input"><legend>Phone</legend><label for="country">Country</label><input id="country" role="combobox" aria-required="true"><input id="phone" type="tel" aria-label="Phone"></fieldset>
      <label for="address-country">Country</label><input id="address-country" role="combobox">`;
    const report = run({
      phone_country_code: "+1",
      phone_country_region: "United States",
      country: "United States",
    });
    expect(
      (
        report.leftovers.find(
          (item) =>
            item.label === "Country" && (item as { key?: string }).key === "phone_country_code",
        ) as { key?: string } | undefined
      )?.key,
    ).toBe("phone_country_code");
    expect(
      (
        report.leftovers.find(
          (item) => item.label === "Country" && (item as { key?: string }).key === "country",
        ) as { key?: string } | undefined
      )?.key,
    ).toBe("country");
  });

  it("does not treat misleading substrings as a choice or overwrite existing answers", () => {
    document.body.innerHTML = `<label for="answer">Country</label><select id="answer"><option value="">Select</option><option value="other">United States territories</option></select><input aria-label="Phone" value="5551234567">`;
    const report = run({ country: "United States", phone: "555 010 0199" });
    expect((document.querySelector("#answer") as HTMLSelectElement).value).toBe("");
    expect((document.querySelector("input") as HTMLInputElement).value).toBe("5551234567");
    expect(report.filled.some((item) => item.value === "5551234567" && item.preserved)).toBe(true);
  });

  it("does not count text typed into a custom combobox as a selected option", () => {
    document.body.innerHTML = `<label for="region">Country</label><input id="region" role="combobox" aria-required="true" value="United States">`;
    const report = run({ country: "United States" });
    expect(report.filled).toHaveLength(0);
    expect(report.leftovers[0].reason).toMatch(/observed selection/);
    expect((document.querySelector("#region") as HTMLInputElement).value).toBe("United States");
  });

  it("reports one radio question instead of each option label", () => {
    document.body.innerHTML = `<fieldset><legend>Willing to relocate?</legend><label for="tx">Texas</label><input id="tx" type="radio" name="relocate" required><label for="vt">Vermont</label><input id="vt" type="radio" name="relocate" required></fieldset>`;
    const readiness = window.eval(readinessScript) as (_args: unknown) => string[];
    expect(readiness({})).toEqual(["Willing to relocate?"]);
  });

  it("routes Greenhouse education comboboxes, fills the end year, and answers salary", () => {
    document.body.innerHTML = `
      <label for="school--0">School</label><input id="school--0" role="combobox">
      <label for="degree--0">Degree</label><input id="degree--0" role="combobox" required>
      <label for="discipline--0">Discipline</label><input id="discipline--0" role="combobox">
      <label for="end-year--0">End date year</label><input id="end-year--0" type="number">
      <label for="salary">What is your desired salary?</label><input id="salary" value="">
    `;
    const report = run(
      {
        school: "University of California - Irvine",
        degree_level: "Bachelors",
        major: "Computer Science",
        graduation_month: "2027-06",
        salary_expectation: "$45/hour",
      },
      { "#school--0": "school", "#degree--0": "degree_level", "#discipline--0": "major" },
    );
    expect(
      report.leftovers
        .filter((item) => ["School", "Degree", "Discipline"].includes(item.label))
        .map((item) => (item as { key?: string }).key),
    ).toEqual(["school", "degree_level", "major"]);
    expect((document.querySelector("#end-year--0") as HTMLInputElement).value).toBe("2027");
    expect((document.querySelector("#salary") as HTMLInputElement).value).toBe("$45/hour");
    expect(report.filled.find((item) => item.key === "salary_expectation")?.value).toBe("$45/hour");
  });

  it("answers salary in the unit and format the question asks for, and leaves it open without a range", () => {
    document.body.innerHTML = `
      <label for="hourly">Desired hourly pay rate</label><input id="hourly" type="number">
      <label for="annual">Expected annual salary</label><input id="annual">
    `;
    run({
      salary_expectation: "$45/hour",
      salary_hourly: "$45/hour",
      salary_hourly_number: "45",
      salary_yearly: "$80,000/year",
      salary_yearly_number: "80000",
    });
    expect((document.querySelector("#hourly") as HTMLInputElement).value).toBe("45");
    expect((document.querySelector("#annual") as HTMLInputElement).value).toBe("$80,000/year");
    document.body.innerHTML = `<label for="salary">Salary expectations</label><input id="salary" required>`;
    const report = run({});
    expect(report.leftovers[0].reason).toMatch(/No salary range/);
  });

  it("reads a Workday questionnaire label from a multi-id aria-labelledby or its form field", () => {
    document.body.innerHTML = `
      <div data-automation-id="formField-q1"><label id="q1-label">What are your salary expectations for this role?</label>
        <textarea id="primaryQuestionnaire--q1" rows="4" aria-labelledby="q1-label q1-error"></textarea><span id="q1-error">Required</span></div>
      <div data-automation-id="formField-q2"><label>What are your salary expectations?</label><textarea id="primaryQuestionnaire--q2" rows="4"></textarea></div>`;
    const report = run({ salary_expectation: "$45/hour" });
    expect((document.querySelector("#primaryQuestionnaire--q1") as HTMLTextAreaElement).value).toBe(
      "$45/hour",
    );
    expect((document.querySelector("#primaryQuestionnaire--q2") as HTMLTextAreaElement).value).toBe(
      "$45/hour",
    );
    expect(report.leftovers).toHaveLength(0);
  });

  it("does not answer a long question from a short-field synonym it happens to mention", () => {
    document.body.innerHTML = `<label for="other">Indicate any other names under which your school or employment records may be identified.</label><textarea id="other"></textarea>`;
    const report = run({ school: "University of California - Irvine" }, {}, [
      ["school|university|college", "school"],
    ]);
    expect((document.querySelector("#other") as HTMLTextAreaElement).value).toBe("");
    expect(report.leftovers[0].reason).toBe("Unrecognized field");
  });

  it("ticks Workday's lone preferred-name checkbox and reports that fields may have appeared", () => {
    document.body.innerHTML = `<input type="checkbox" id="name--preferredCheck"><label for="name--preferredCheck">I have a preferred name</label>`;
    const report = run({ has_preferred_name: "Yes", preferred_name: "Alex" }) as FillReport & {
      revealed?: boolean;
    };
    expect((document.querySelector("#name--preferredCheck") as HTMLInputElement).checked).toBe(
      true,
    );
    expect(report.revealed).toBe(true);
    expect(report.leftovers).toHaveLength(0);
    document.body.insertAdjacentHTML(
      "beforeend",
      `<label for="name--preferredName--firstName">First Name</label><input id="name--preferredName--firstName">`,
    );
    const again = run(
      { has_preferred_name: "Yes", preferred_name: "Alex", first_name: "Legal" },
      {},
      [["first name", "first_name"]],
    ) as FillReport & { revealed?: boolean };
    expect(
      (document.querySelector("#name--preferredName--firstName") as HTMLInputElement).value,
    ).toBe("Alex");
    expect(again.revealed).toBe(false);
  });

  it("uses the preferred name and formats a full availability date", () => {
    document.body.innerHTML = `
      <label for="first_name">First Name</label><input id="first_name">
      <label for="preferred">Preferred First Name</label><input id="preferred">
      <label for="start">When can you start?</label><input id="start">
    `;
    const report = run(
      { first_name: "Legal", preferred_name: "Alex", earliest_start: "2027-06-14" },
      {},
      [
        ["preferred first name|preferred name", "preferred_name"],
        ["first name", "first_name"],
        ["when can you start|start date", "earliest_start"],
      ],
    );
    expect((document.querySelector("#first_name") as HTMLInputElement).value).toBe("Legal");
    expect((document.querySelector("#preferred") as HTMLInputElement).value).toBe("Alex");
    expect((document.querySelector("#start") as HTMLInputElement).value).toBe("June 14, 2027");
    expect(report.filled).toHaveLength(3);
  });

  it("classifies Hispanic/Latino separately from a conditional race dropdown", () => {
    document.body.innerHTML = `
      <label for="hispanic">Are you Hispanic/Latino?</label><input id="hispanic" role="combobox">
      <label for="race">Race</label><input id="race" role="combobox">
    `;
    const report = run(
      { hispanic_latino: "No", race: "Asian", race_detail: "Southeast Asian" },
      {},
      [
        ["hispanic|latino", "hispanic_latino"],
        ["race|ethnicity", "race"],
      ],
    );
    expect(report.leftovers.map((item) => (item as { key?: string }).key)).toEqual([
      "hispanic_latino",
      "race",
    ]);
  });
});
