import { describe, expect, it, vi } from "vitest";
import { applicationColumns } from "./applicationColumns";

const actions = {} as Parameters<typeof applicationColumns>[0]["actions"];
const ids = (simple: boolean, scope: "queue" | "review" | "archive", extra: string[] = []) =>
  applicationColumns({ scope, actions, extraColumns: extra, navigate: vi.fn(), simple }).map(
    (column) => column.id,
  );

describe("applicationColumns in Simple view", () => {
  it("leads In progress with the match and drops Platform and optional columns", () => {
    expect(ids(true, "queue", ["salary"])).toEqual([
      "coverage",
      "company",
      "role",
      "posted_at",
      "status",
      "actions",
    ]);
  });

  it("keeps every column in Full view", () => {
    expect(ids(false, "queue", ["salary"])).toEqual([
      "company",
      "role",
      "ats",
      "posted_at",
      "coverage",
      "status",
      "salary",
      "actions",
    ]);
  });

  it("keeps the reason and waiting time on Needs you", () => {
    expect(ids(true, "review")).toEqual(["company", "role", "status", "status_at", "actions"]);
  });
});
