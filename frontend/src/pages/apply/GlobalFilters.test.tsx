// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApplySettings, SourceConfig } from "../../api";
import { DEFAULT_SETTINGS } from "../../state/runDefaults";
import { EverySourceContext } from "./everySource";
import { FiltersEditor } from "./FiltersEditor";
import { GlobalFiltersTile } from "./GlobalFiltersTile";

afterEach(cleanup);

const apply: ApplySettings = {
  ...DEFAULT_SETTINGS.apply,
  source_filters: {
    include: ["analyst"],
    exclude: ["senior", "director", "principal"],
    locations: [],
  },
};

const watchlist: SourceConfig = {
  id: "w",
  kind: "ats_board",
  url: "",
  categories: [],
  enabled: true,
  include: ["associate"],
  exclude: [],
  locations: [],
  max_age_days: 7,
};

describe("GlobalFiltersTile", () => {
  function Harness({ onChange }: { onChange: (patch: Partial<ApplySettings>) => void }) {
    const [editing, setEditing] = useState(false);
    return (
      <GlobalFiltersTile
        apply={apply}
        onChange={onChange}
        editing={editing}
        onEditingChange={setEditing}
      />
    );
  }

  it("lists the current filters, and Change opens the form in place", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    expect(screen.getByText("senior, director +1 more")).toBeTruthy();
    expect(screen.getByText("Anywhere")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(screen.getByRole("button", { name: "Done" }).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(screen.getByRole("switch", { name: /won't sponsor a visa/ }));
    expect(onChange).toHaveBeenCalledWith({
      exclude_no_sponsorship: !apply.exclude_no_sponsorship,
    });

    const skip = screen.getByRole("textbox", { name: "Skip titles containing" });
    fireEvent.change(skip, { target: { value: "staff" } });
    fireEvent.keyDown(skip, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith({
      source_filters: {
        ...apply.source_filters,
        exclude: ["senior", "director", "principal", "staff"],
      },
    });
  });
});

describe("FiltersEditor with filters for every source", () => {
  function renderEditor(source: SourceConfig, onChange = vi.fn(), openGlobal = vi.fn()) {
    render(
      <EverySourceContext.Provider
        value={{ filters: apply.source_filters!, eligibility: "Skips 4+ years", openGlobal }}
      >
        <FiltersEditor source={source} onChange={onChange} defaultDays={7} canChangeGlobal />
      </EverySourceContext.Provider>,
    );
    return { onChange, openGlobal };
  }

  it("shows global words as locked chips beside the source's own", () => {
    const { openGlobal } = renderEditor(watchlist);
    const keep = screen.getByRole("list", { name: "Keep titles containing" });
    expect(within(keep).getByText(/analyst/)).toBeTruthy();
    expect(within(keep).queryByRole("button", { name: /Remove keyword analyst/ })).toBeNull();
    expect(within(keep).getByRole("button", { name: "Remove keyword associate" })).toBeTruthy();
    expect(screen.getByText(/Skips 4\+ years/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Change them there" }));
    expect(openGlobal).toHaveBeenCalled();
  });

  it("does not add a word that is already global, and can opt out of the keep words", () => {
    const { onChange } = renderEditor(watchlist);
    const box = screen.getByRole("textbox", { name: "Skip titles containing" });
    fireEvent.change(box, { target: { value: "Senior" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Don't use the global keep words for this source"));
    expect(onChange).toHaveBeenCalledWith({ ...watchlist, ignore_global_include: true });
  });
});
