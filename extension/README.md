# ResumeTailor browser extension

1. Start ResumeTailor on `127.0.0.1` (port 8000–8010).
2. Open `chrome://extensions` or `edge://extensions`, turn on **Developer mode**, choose
   **Load unpacked**, and select this `extension/` folder.
3. In ResumeTailor, open **Settings → Browser** and choose **Pair a browser**.
4. Open the extension popup, enter the six-digit code, and choose **Pair**.

Use **Send to ResumeTailor** to capture a job page. **Tailor now** prepares it.
**Fill this page** prepares an untracked job and automatically starts Fill when it is
ready, even if the popup closes. It never enables automatic submission. Fill currently
uses ResumeTailor's configured browser; check the form and submit it yourself.
LinkedIn, Indeed, Handshake, and Workday are assist-only.

## Fill the selected tab through the relay

The normal CDP browser mode remains the default. For the optional relay, run the app
and relay on the same host and with the same `RESUME_TAILOR_DATA_DIR`. After pairing:

1. Start `python -m resume_tailor.apply.cdp_relay` in a separate terminal. It prints a
   one-time `ws://127.0.0.1:8011/cdp/...` URL.
2. Start ResumeTailor with `BROWSER_MODE=extension` and `EXTENSION_CDP_URL` set to that
   exact URL. Restarting the relay creates a new URL, so restart the app with it.
3. On the job tab, choose **Use this tab for Fill (relay)** in the popup, then use
   **Fill this page**. Keep that tab open; opening DevTools detaches it. The app leaves
   the filled form for your review and submission.

The relay binds only to `127.0.0.1:8011`. Its CDP URL contains a temporary secret.
The extension's `debugger` permission is used only after you attach the selected tab.
The relay reuses that tab when Fill requests a new page. Only one tab can be attached
at a time; detach by closing the tab or stopping the relay. This mode was checked on
a synthetic Greenhouse-like page in Edge, not live job sites.

If a page shows a login wall or its job description is hidden in a cross-origin iCIMS
iframe, select the description and use **Send selection to ResumeTailor** from the
context menu. You can also open an iframe's job URL as its own tab and capture there.

The extension talks only to `127.0.0.1` ports 8000–8010 and, when enabled, the relay
on port 8011. Opening the popup sends the
current page URL to the local app for lookup. JD text is sent only after you use a
capture command. The extension does not fetch external job sites and does not receive
your resume or model keys. Pairing tokens stay in extension local storage; revoke a
browser from Settings to invalidate its token.
