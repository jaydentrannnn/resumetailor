// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const failed = {
  running: false,
  error: "Skill detection skipped (offline)",
  waiting: 2,
  bullets: {},
};
const restarted = { ...failed, running: true };
const done = { running: false, error: null, waiting: 0, bullets: {} };

const fetchBulletSkills = vi.fn();
const refreshBulletSkills = vi.fn();

vi.mock("../api", () => ({
  fetchBulletSkills: () => fetchBulletSkills(),
  refreshBulletSkills: () => refreshBulletSkills(),
}));

import { BulletSkillsNotice } from "../pages/editor/BulletSkillsNotice";
import { BulletSkillsProvider } from "./bulletSkillsState";

beforeEach(() => {
  fetchBulletSkills.mockReset();
  refreshBulletSkills.mockReset();
});
afterEach(() => cleanup());

function mount() {
  return render(
    <BulletSkillsProvider dirty={false}>
      <BulletSkillsNotice />
    </BulletSkillsProvider>,
  );
}

it("retries a failed detection once when the editor opens", async () => {
  fetchBulletSkills.mockResolvedValue(failed);
  refreshBulletSkills.mockResolvedValue(restarted);
  mount();
  await waitFor(() => expect(refreshBulletSkills).toHaveBeenCalledTimes(1));
  // Running again: no failure note while the retry works.
  expect(screen.queryByRole("status")).toBeNull();
});

it("shows the quiet note when the retry fails too, without retrying again", async () => {
  fetchBulletSkills.mockResolvedValue(failed);
  refreshBulletSkills.mockResolvedValue(failed);
  mount();
  const note = await screen.findByRole("status");
  expect(note.textContent).toContain("Skill detection didn't finish (Skill detection skipped");
  expect(refreshBulletSkills).toHaveBeenCalledTimes(1);
});

it("stays silent once every bullet has its skills", async () => {
  fetchBulletSkills.mockResolvedValue(done);
  mount();
  await waitFor(() => expect(fetchBulletSkills).toHaveBeenCalled());
  expect(refreshBulletSkills).not.toHaveBeenCalled();
  expect(screen.queryByRole("status")).toBeNull();
});
