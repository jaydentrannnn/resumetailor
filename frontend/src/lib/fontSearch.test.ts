import { expect, it } from "vitest";
import { fontGroups, isInstalled } from "./fontSearch";

const families = ["Arial", "Arial Narrow", "Calibri", "Fira Sans", "Georgia", "Sans Serif Pro"];
const common = ["Arial", "Calibri", "Georgia"];

it("lists common fonts first and the rest once", () => {
  expect(fontGroups(families, common, "")).toEqual([
    { label: "Common", fonts: ["Arial", "Calibri", "Georgia"] },
    { label: "All installed", fonts: ["Arial Narrow", "Fira Sans", "Sans Serif Pro"] },
  ]);
});

it("filters by what was typed, names starting with it first", () => {
  expect(fontGroups(families, common, "sans")).toEqual([
    { label: "All installed", fonts: ["Sans Serif Pro", "Fira Sans"] },
  ]);
  expect(fontGroups(families, common, "zzz")).toEqual([]);
});

it("matches installed names without regard to case", () => {
  expect(isInstalled("georgia ", families)).toBe(true);
  expect(isInstalled("Helvetica", families)).toBe(false);
});
