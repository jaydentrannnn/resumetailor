import { DOCUMENT_FIRST } from "../../../lib/viewer";

/**
 * The Template page's grid, every view and Quick adjustments alike: the document on the
 * left, one page wide at the window's height and sticky while the tools scroll; the tools
 * on the right, taking the rest of the width. Below `lg` the cells stack, document first.
 */
export const WORKSPACE_GRID = `grid min-w-0 items-start gap-6 lg:gap-8 ${DOCUMENT_FIRST}`;
export const DOCUMENT_CELL = "min-w-0 lg:sticky lg:top-[calc(var(--rt-bar-top)+1.25rem)]";
export const TOOLS_CELL = "min-w-0 space-y-5";
