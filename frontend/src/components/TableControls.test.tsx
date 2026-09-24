// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DataTable, Pagination } from "./TableControls";

const rows = [{ id: "a", name: "Alpha" }, { id: "b", name: "Beta" }];
const columns = [{ id: "name", heading: "Name", cell: (row: typeof rows[number]) => row.name, sortable: true }];
afterEach(cleanup);

describe("shared table controls", () => {
  it("selects only rows passed to the current page", () => {
    const onSelected = vi.fn();
    render(<DataTable rows={rows} id={row => row.id} columns={columns} selected={new Set()} onSelected={onSelected} sort="name" direction="asc" onSort={() => {}} empty="Empty" />);
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select this page" })[0]);
    expect([...onSelected.mock.lastCall![0]]).toEqual(["a", "b"]);
  });
  it("marks a partial page selection indeterminate", () => {
    render(<DataTable rows={rows} id={row => row.id} columns={columns} selected={new Set(["a"])} onSelected={() => {}} sort="name" direction="asc" onSort={() => {}} empty="Empty" />);
    expect((document.querySelector("thead input") as HTMLInputElement).indeterminate).toBe(true);
  });
  it("selects only eligible rows", () => {
    const onSelected = vi.fn();
    render(<DataTable rows={rows} id={row => row.id} columns={columns} selected={new Set()} onSelected={onSelected} selectable={row => row.id === "a"} sort="name" direction="asc" onSort={() => {}} empty="Empty" />);
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select this page" })[0]);
    expect([...onSelected.mock.lastCall![0]]).toEqual(["a"]);
  });
  it("shows an empty range with disabled navigation", () => {
    render(<Pagination page={0} size={25} total={0} onPage={() => {}} onSize={() => {}} />);
    expect(screen.getByText("0 results")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Next" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
