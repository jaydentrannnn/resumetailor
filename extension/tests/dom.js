// Load a saved page into jsdom with the extension's classic scripts bound to its window.
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

export function loadPage(fixture, url, scripts = ["lib/sites.js", "lib/applyLink.js"]) {
  const html = fixture.startsWith("<") ? fixture : read(`tests/fixtures/${fixture}`);
  const dom = new JSDOM(html, { url, runScripts: "outside-only" });
  for (const script of scripts) dom.window.eval(read(script));
  return dom.window;
}

export function runExtract(window) {
  return window.eval(read("extract.js"));
}
