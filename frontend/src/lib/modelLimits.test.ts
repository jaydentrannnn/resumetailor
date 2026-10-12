import { describe, expect, it } from "vitest";
import { limitLabel } from "./modelLimits";

const endpoint = {
  endpoint: "https://gemini.example/v1",
  local: false,
  limit: 1,
  active: 0,
  waiting: 0,
  cooldown_seconds: 0,
  exhausted_seconds: 0,
};
const status = (overrides: Partial<typeof endpoint>) => ({
  settings: { local_concurrency: 1, cloud_concurrency: 3, endpoint_limits: {} },
  roles: { heavy: "https://gemini.example/v1" },
  endpoints: [{ ...endpoint, ...overrides }],
});
const now = new Date(2026, 9, 12, 14, 0, 0);

describe("limitLabel", () => {
  it("is null for a role with no limit, or no known server", () => {
    expect(limitLabel(status({}), "heavy", now)).toBeNull();
    expect(limitLabel(status({ cooldown_seconds: 30 }), "light", now)).toBeNull();
    expect(limitLabel(null, "heavy", now)).toBeNull();
  });

  it("names the time a cooldown or a used-up quota ends", () => {
    expect(limitLabel(status({ cooldown_seconds: 300 }), "heavy", now)).toMatch(
      /^At limit, resumes /,
    );
    expect(limitLabel(status({ exhausted_seconds: 600 }), "heavy", now)).toMatch(
      /^Quota used up, resumes /,
    );
    expect(limitLabel(status({ exhausted_seconds: 7200 }), "heavy", now)).toBe(
      "Quota used up for now",
    );
  });
});
