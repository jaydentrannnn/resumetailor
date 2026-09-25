# ResumeTailor browser extension

1. Start ResumeTailor on `127.0.0.1` (port 8000–8010).
2. Open `chrome://extensions` or `edge://extensions`, turn on **Developer mode**, choose
   **Load unpacked**, and select this `extension/` folder.
3. In ResumeTailor, open **Settings → Browser** and choose **Pair a browser**.
4. Open the extension popup, enter the six-digit code, and choose **Pair**.

Use **Send to ResumeTailor** to capture a job page. **Tailor now** prepares it.
**Fill this page** prepares an untracked job and automatically starts Fill when it is
ready, even if the popup closes. It never enables automatic submission. Fill currently
uses ResumeTailor's separately configured CDP browser; check the form and submit it
yourself. LinkedIn, Indeed, Handshake, and Workday are assist-only.

If a page shows a login wall or its job description is hidden in a cross-origin iCIMS
iframe, select the description and use **Send selection to ResumeTailor** from the
context menu. You can also open an iframe's job URL as its own tab and capture there.

The extension talks only to `127.0.0.1` ports 8000–8010. Opening the popup sends the
current page URL to the local app for lookup. JD text is sent only after you use a
capture command. The extension does not fetch external job sites and does not receive
your resume or model keys. Pairing tokens stay in extension local storage; revoke a
browser from Settings to invalidate its token.
