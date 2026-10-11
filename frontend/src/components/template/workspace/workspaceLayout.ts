/**
 * The Template tile's grid (the tile itself has no padding). From `lg` up: the document
 * fills the left column with the same 20px margin on its top, left and bottom edges; the
 * right column holds the view switch, then the tools for that view, with an even 20px on
 * its top, right and left (the column gap). 316px less its 20px right margin leaves the
 * tools 296px, the width the Word session's three buttons are sized for. Below `lg` the
 * cells stack in source order (switch, document, tools) inside the usual tile padding.
 */
export const WORKSPACE_GRID =
  "grid min-w-0 gap-6 p-5 sm:px-6 lg:grid-cols-[minmax(0,1fr)_316px] lg:grid-rows-[auto_1fr] lg:gap-5 lg:p-0";
export const SWITCH_CELL = "min-w-0 lg:col-start-2 lg:row-start-1 lg:pr-5 lg:pt-5";
export const DOCUMENT_CELL = "min-w-0 lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:py-5 lg:pl-5";
export const TOOLS_CELL = "min-w-0 space-y-5 lg:col-start-2 lg:row-start-2 lg:pb-5 lg:pr-5";
