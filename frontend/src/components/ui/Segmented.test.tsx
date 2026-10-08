// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Tabs } from "../Tabs";
import { Segmented } from "./Segmented";

afterEach(cleanup);

const tabIndexes = (role: "radio" | "tab") =>
  screen.getAllByRole(role).map((item) => item.getAttribute("tabindex"));

describe("roving tab stop", () => {
  it("Segmented keeps the first enabled item tabbable when value matches nothing", () => {
    render(
      <Segmented
        label="Show"
        value="gone"
        onChange={() => {}}
        items={[
          { id: "a", label: "A", disabled: true },
          { id: "b", label: "B" },
          { id: "c", label: "C" },
        ]}
      />,
    );
    expect(tabIndexes("radio")).toEqual(["-1", "0", "-1"]);
  });

  it("Segmented puts the tab stop on the selected item", () => {
    render(
      <Segmented
        label="Show"
        value="c"
        onChange={() => {}}
        items={[
          { id: "b", label: "B" },
          { id: "c", label: "C" },
        ]}
      />,
    );
    expect(tabIndexes("radio")).toEqual(["-1", "0"]);
  });

  it("Tabs keeps the first tab tabbable when value matches nothing", () => {
    render(
      <Tabs
        label="Views"
        value="gone"
        onChange={() => {}}
        items={[
          { id: "a", label: "A" },
          { id: "b", label: "B" },
        ]}
      />,
    );
    expect(tabIndexes("tab")).toEqual(["0", "-1"]);
  });
});
