// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, expect, it } from "vitest";

const script = readFileSync(resolve(process.cwd(), "../src/resume_tailor/apply/dom_scan.js"), "utf8");

function scan(): { fields: Array<{ label: string; control_kind: string; current_value: string; section_id: string; options: Array<{ label: string }> }> } {
  const inspect = window.eval(script) as () => ReturnType<typeof scan>;
  return inspect();
}

beforeEach(() => {
  document.body.innerHTML = "";
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true, value: () => ({ width: 100, height: 20 }),
  });
});

it("observes labelled controls and radio groups without changing the form", () => {
  document.body.innerHTML = `
    <span id="first">Preferred</span><span id="second">First Name</span>
    <input id="preferred" aria-labelledby="first second" value="Jay">
    <fieldset><legend>Phone</legend><label for="country">Country</label>
      <select id="country"><option value="">Select</option><option value="us" selected>United States +1</option></select>
      <input type="tel" aria-label="Phone">
    </fieldset>
    <fieldset><legend>Are you Hispanic/Latino?</legend>
      <label><input type="radio" name="ethnicity" value="yes">Yes</label>
      <label><input type="radio" name="ethnicity" value="no" checked>No</label>
    </fieldset>`;
  const before = document.body.innerHTML;
  const result = scan();
  expect(document.body.innerHTML).toBe(before);
  expect(result.fields.find(field => field.label === "Preferred First Name")?.current_value).toBe("Jay");
  expect(result.fields.find(field => field.label === "Country")?.current_value).toBe("United States +1");
  expect(result.fields.find(field => field.control_kind === "radio_group")?.options).toHaveLength(2);
  expect(result.fields.find(field => field.control_kind === "radio_group")?.current_value).toContain("No");
});

it("does not report typed autocomplete search text as a committed selection", () => {
  document.body.innerHTML = `<label for="degree">Degree</label><div class="select__control"><input id="degree" role="combobox" value="bachelor"></div>`;
  expect(scan().fields.find(field => field.label === "Degree")?.current_value).toBe("");
});
