// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { clickSelect, isRowSelectClick, rangeSelect } from "./rowSelection";

const click = (target: Element, extra: Partial<MouseEventInit> = {}) => ({
  target,
  button: 0,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  ...extra,
});

function row(html: string) {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.append(el);
  return el;
}
afterEach(() => {
  document.body.innerHTML = "";
  window.getSelection()?.removeAllRanges();
});

describe("isRowSelectClick", () => {
  it("selects on plain text but not on the row's own controls", () => {
    const r = row(
      '<span id="t">Acme</span><a id="a" href="#"><b id="ab">x</b></a><button id="b">Go</button>' +
        '<div data-row-select="off"><span id="off">near</span></div><div role="switch" id="s"></div>',
    );
    expect(isRowSelectClick(click(r.querySelector("#t")!), r)).toBe(true);
    for (const id of ["a", "ab", "b", "off", "s"])
      expect(isRowSelectClick(click(r.querySelector(`#${id}`)!), r)).toBe(false);
  });
  it("ignores modified, non-primary and outside-the-row (portal) clicks", () => {
    const r = row('<span id="t">Acme</span>');
    const t = r.querySelector("#t")!;
    expect(isRowSelectClick(click(t, { ctrlKey: true }), r)).toBe(false);
    expect(isRowSelectClick(click(t, { button: 2 }), r)).toBe(false);
    const portal = row('<span id="p">Archive</span>');
    expect(isRowSelectClick(click(portal.querySelector("#p")!), r)).toBe(false);
  });
  it("leaves a text highlight alone", () => {
    const r = row('<span id="t">Acme Corp</span>');
    const range = document.createRange();
    range.selectNodeContents(r.querySelector("#t")!);
    window.getSelection()!.addRange(range);
    expect(isRowSelectClick(click(r.querySelector("#t")!), r)).toBe(false);
  });
});

describe("rangeSelect", () => {
  const ids = ["a", "b", "c", "d", "e"];
  it("ticks a range in either direction, skipping ineligible rows", () => {
    const eligible = (id: string) => id !== "c";
    expect([...rangeSelect(new Set(["b"]), ids, eligible, "b", "e")!].sort()).toEqual([
      "b",
      "d",
      "e",
    ]);
    expect([...rangeSelect(new Set(["d"]), ids, eligible, "d", "a")!].sort()).toEqual([
      "a",
      "b",
      "d",
    ]);
  });
  it("unticks the range when the anchor is unticked", () => {
    const next = rangeSelect(new Set(["a", "c", "d"]), ids, () => true, "b", "d")!;
    expect([...next]).toEqual(["a"]);
  });
  it("gives null when an end is not in the list", () => {
    expect(rangeSelect(new Set(), ids, () => true, "z", "a")).toBeNull();
  });
});

describe("clickSelect", () => {
  it("toggles, remembers the anchor, then ranges on Shift", () => {
    const anchor = { current: null as string | null };
    const ids = ["a", "b", "c"];
    let selected = clickSelect(new Set(), ids, () => true, anchor, "a", false);
    expect([...selected]).toEqual(["a"]);
    expect(anchor.current).toBe("a");
    selected = clickSelect(selected, ids, () => true, anchor, "c", true);
    expect([...selected].sort()).toEqual(["a", "b", "c"]);
  });
  it("Shift with no anchor is a plain toggle", () => {
    const anchor = { current: null as string | null };
    expect([...clickSelect(new Set(), ["a", "b"], () => true, anchor, "b", true)]).toEqual(["b"]);
  });
});
