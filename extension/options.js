import { findPort } from "./lib/api.js";
import { BOARD_ORIGINS, hasBoardAccess, requestBoardAccess, syncBoardScripts } from "./lib/boards.js";
import { getOptions, parsePort, setOptions } from "./lib/settings.js";

const $ = (selector) => document.querySelector(selector);
const saved = $("#saved");

function flash(message) {
  saved.textContent = message;
  window.setTimeout(() => { if (saved.textContent === message) saved.textContent = ""; }, 2500);
}

async function save(patch) {
  await setOptions(patch);
  flash("Saved.");
}

async function showBoards() {
  const granted = await hasBoardAccess();
  $("#boards-status").textContent = granted
    ? "Allowed. The chip and automatic completion work on LinkedIn and Indeed job pages."
    : "Not allowed yet. Saving cards from the popup still works; allow access to complete them automatically.";
  $("#boards-allow").hidden = granted;
  $("#boards-remove").hidden = !granted;
}

async function showShortcut() {
  const commands = await chrome.commands.getAll();
  const capture = commands.find((command) => command.name === "capture-page");
  $("#shortcut").textContent = capture?.shortcut || "not set";
}

async function load() {
  const options = await getOptions();
  $("#port").value = options.port ? String(options.port) : "";
  for (const radio of document.querySelectorAll("input[name='afterCapture']")) {
    radio.checked = radio.value === options.afterCapture;
    radio.addEventListener("change", () => { if (radio.checked) void save({ afterCapture: radio.value }); });
  }
  $("#page-chip").checked = options.pageChip;
  $("#auto-complete").checked = options.autoComplete;
  $("#relay").checked = options.relay && (await chrome.permissions.contains({ permissions: ["debugger"] }));
  await showBoards();
  await showShortcut();
}

$("#port").addEventListener("change", async () => {
  try {
    await save({ port: parsePort($("#port").value) });
    $("#port-status").textContent = "";
  } catch (error) {
    $("#port-status").textContent = error.message;
  }
});

$("#test-port").addEventListener("click", async () => {
  const status = $("#port-status");
  try {
    await save({ port: parsePort($("#port").value) });
    status.textContent = `Connected to ResumeTailor on port ${await findPort()}.`;
  } catch (error) {
    status.textContent = error.message;
  }
});

$("#page-chip").addEventListener("change", (event) => void save({ pageChip: event.target.checked }));
$("#auto-complete").addEventListener("change", (event) => void save({ autoComplete: event.target.checked }));

$("#boards-allow").addEventListener("click", async () => {
  await requestBoardAccess();
  await showBoards();
});
$("#boards-remove").addEventListener("click", async () => {
  await chrome.permissions.remove({ origins: BOARD_ORIGINS });
  await syncBoardScripts();
  await showBoards();
});

$("#relay").addEventListener("change", async (event) => {
  const box = event.target;
  if (box.checked) {
    // The only place `debugger` is requested: turning the relay on.
    const granted = await chrome.permissions.request({ permissions: ["debugger"] });
    box.checked = granted;
    await save({ relay: granted });
  } else {
    await chrome.permissions.remove({ permissions: ["debugger"] });
    await save({ relay: false });
  }
});

$("#shortcuts").addEventListener("click", (event) => {
  event.preventDefault();
  const url = navigator.userAgent.includes("Edg/") ? "edge://extensions/shortcuts" : "chrome://extensions/shortcuts";
  void chrome.tabs.create({ url });
});

void load();
