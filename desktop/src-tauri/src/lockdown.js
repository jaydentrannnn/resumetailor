// Desktop window lockdown: switches off the browser behaviours that make no sense in an
// app window (reload, history navigation, the browser's own menus, print-page,
// save-page, view-source, find bar, page zoom, new windows, file drops that would open
// the file in place of the app). Injected by the shell into every page of the main
// window before any page script runs; the browser build (Docker, uvicorn) never gets it.
//
// Only `preventDefault()`, never `stopPropagation()`: the app still sees every key and
// click, so its own shortcuts (Ctrl+S, Ctrl+F, Ctrl+P, ...) and its text-field menu work.
// `window.__RT_DEBUG__` (set by the shell) keeps DevTools keys in debug builds.
(function () {
  if (window.__RT_LOCKDOWN__) return;
  window.__RT_LOCKDOWN__ = true;
  var debug = window.__RT_DEBUG__ === true;

  // Ctrl/Cmd + key (lower-case `key`) that the browser would act on.
  var CTRL_KEYS = {
    r: 1, p: 1, s: 1, u: 1, o: 1, f: 1, g: 1, j: 1, h: 1, n: 1, t: 1, w: 1, l: 1,
    "=": 1, "+": 1, "-": 1, _: 1, "0": 1,
  };
  var DEVTOOLS_SHIFT_KEYS = { i: 1, j: 1, c: 1 };

  function blockedKey(e) {
    var key = (e.key || "").toLowerCase();
    var ctrl = e.ctrlKey || e.metaKey;
    if (key === "f5" || key === "browserrefresh") return true;
    if (key === "browserback" || key === "browserforward") return true;
    if (key === "f3" || key === "f7") return true;
    if (e.altKey && (key === "arrowleft" || key === "arrowright" || key === "home")) return true;
    if (ctrl && e.shiftKey && key === "delete") return true;
    if (key === "f12" || (ctrl && e.shiftKey && DEVTOOLS_SHIFT_KEYS[key])) return !debug;
    if (ctrl && CTRL_KEYS[key]) return true;
    return false;
  }

  window.addEventListener(
    "keydown",
    function (e) {
      if (blockedKey(e)) e.preventDefault();
    },
    true,
  );

  // Mouse back / forward buttons (3, 4) navigate history; middle-click (1) on a link
  // opens a second app window.
  function blockButtons(e) {
    if (e.button === 3 || e.button === 4) e.preventDefault();
  }
  ["mousedown", "mouseup", "pointerup", "auxclick"].forEach(function (type) {
    window.addEventListener(type, blockButtons, true);
  });
  window.addEventListener(
    "auxclick",
    function (e) {
      if (e.button === 1 && e.target instanceof Element && e.target.closest("a[href]")) {
        e.preventDefault();
      }
    },
    true,
  );

  // Ctrl/Shift/Cmd-click on an in-app link would open it in a new window.
  window.addEventListener(
    "click",
    function (e) {
      if (!(e.ctrlKey || e.shiftKey || e.metaKey)) return;
      var link = e.target instanceof Element ? e.target.closest("a[href]") : null;
      if (link && link.getAttribute("target") !== "_blank") e.preventDefault();
    },
    true,
  );

  // The browser's menu (Back, Reload, Save as, Print, Inspect). The app draws its own
  // Cut / Copy / Paste / Select all menu for text.
  window.addEventListener(
    "contextmenu",
    function (e) {
      e.preventDefault();
    },
    true,
  );

  // A file dropped outside a drop zone would replace the app with that file.
  function outsideDropZone(e) {
    var types = e.dataTransfer ? Array.prototype.slice.call(e.dataTransfer.types || []) : [];
    if (types.indexOf("Files") === -1) return false;
    return !(e.target instanceof Element && e.target.closest("[data-dropzone]"));
  }
  window.addEventListener("dragover", function (e) {
    if (!outsideDropZone(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "none";
  });
  window.addEventListener("drop", function (e) {
    if (outsideDropZone(e)) e.preventDefault();
  });

  // Ctrl + wheel / pinch zooms the whole page.
  window.addEventListener(
    "wheel",
    function (e) {
      if (e.ctrlKey) e.preventDefault();
    },
    { capture: true, passive: false },
  );
})();
