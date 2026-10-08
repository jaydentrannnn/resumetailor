import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-hosted fonts (no Google Fonts request: the desktop app may run offline). Fraunces
// ships its optical-size axis so large titles get the display cut.
import "@fontsource-variable/fraunces/opsz.css";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import App from "./App";
import "./index.css";

// The server's sign-in redirect appends `?v=<version>` as a cache-buster for the page.
const bootUrl = new URL(window.location.href);
if (bootUrl.searchParams.has("v")) {
  bootUrl.searchParams.delete("v");
  window.history.replaceState(null, "", bootUrl.pathname + bootUrl.search + bootUrl.hash);
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
