/**
 * The Template tile's grid (the tile itself has no padding). From `lg` up, as on Tailor:
 * the left column holds the view switch, then the tools for that view, with an even 20px
 * on its top, left and right (the column gap); the document fills the right column with
 * the same 20px margin on its top, right and bottom edges. 316px less its 20px left
 * margin leaves the tools 296px, the width the Word session's three buttons are sized
 * for. Below `lg` the cells stack in source order (switch, document, tools) inside the
 * usual tile padding.
 */
export const WORKSPACE_GRID =
  "grid min-w-0 gap-6 p-5 sm:px-6 lg:grid-cols-[316px_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:gap-5 lg:p-0";
export const SWITCH_CELL = "min-w-0 lg:col-start-1 lg:row-start-1 lg:pl-5 lg:pt-5";
export const DOCUMENT_CELL = "min-w-0 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:py-5 lg:pr-5";
export const TOOLS_CELL = "min-w-0 space-y-5 lg:col-start-1 lg:row-start-2 lg:pb-5 lg:pl-5";

/**
 * Quick adjustments' grid: the same cells and 20px margins, with a wider left column
 * (420px less its margin leaves 400px) so the settings rows aren't cramped beside the
 * draft preview.
 */
export const ADJUST_GRID =
  "grid min-w-0 gap-6 p-5 sm:px-6 lg:grid-cols-[420px_minmax(0,1fr)] lg:grid-rows-[auto_1fr] lg:gap-5 lg:p-0";
