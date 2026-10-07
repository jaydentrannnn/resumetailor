import { describe, expect, it } from "vitest";
import { composeDate, dateProblem, displayDate, parseDate } from "./dates";

describe("dates", () => {
  it("reads stored shapes into parts and rejects free text", () => {
    expect(parseDate("2027-06-14")).toEqual({ year: "2027", month: "6", day: "14" });
    expect(parseDate("2027-06")).toEqual({ year: "2027", month: "6", day: "" });
    expect(parseDate("2027")).toEqual({ year: "2027", month: "", day: "" });
    expect(parseDate("Present")).toBeNull();
    expect(parseDate("")).toBeNull();
  });

  it("composes only complete, real dates", () => {
    expect(composeDate({ year: "2027", month: "6", day: "" }, "month")).toBe("2027-06");
    expect(composeDate({ year: "2027", month: "6", day: "4" }, "day")).toBe("2027-06-04");
    expect(composeDate({ year: "2027", month: "6", day: "" }, "day")).toBeNull();
    expect(composeDate({ year: "2027", month: "2", day: "30" }, "day")).toBeNull();
    expect(composeDate({ year: "27", month: "6", day: "" }, "month")).toBeNull();
    expect(composeDate({ year: "2027", month: "", day: "" }, "month")).toBeNull();
  });

  it("shows month names", () => {
    expect(displayDate("2027-06")).toBe("June 2027");
    expect(displayDate("2027-06-14")).toBe("June 14, 2027");
    expect(displayDate("Fall 2022")).toBe("Fall 2022");
  });

  it("explains an incomplete date and stays quiet when blank or complete", () => {
    expect(dateProblem({ year: "", month: "", day: "" }, "month")).toBeNull();
    expect(dateProblem({ year: "2027", month: "", day: "" }, "month")).toBe("Pick a month.");
    expect(dateProblem({ year: "20", month: "6", day: "" }, "month")).toBe("Enter a 4-digit year.");
    expect(dateProblem({ year: "2027", month: "6", day: "" }, "day")).toBe("Enter the day.");
    expect(dateProblem({ year: "2027", month: "6", day: "" }, "month")).toBeNull();
  });
});
