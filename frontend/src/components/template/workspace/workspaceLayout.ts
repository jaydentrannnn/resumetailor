/**
 * The Template tile's grid. From `lg` up: the document fills the left column from the
 * tile's top edge to its bottom; the right column holds the view switch, then the tools
 * for that view. Below `lg` the cells stack in source order: switch, document, tools.
 */
export const WORKSPACE_GRID =
  "grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:grid-rows-[auto_1fr]";
export const SWITCH_CELL = "min-w-0 lg:col-start-2 lg:row-start-1";
export const DOCUMENT_CELL = "min-w-0 lg:col-start-1 lg:row-span-2 lg:row-start-1";
export const TOOLS_CELL = "min-w-0 space-y-5 lg:col-start-2 lg:row-start-2";
