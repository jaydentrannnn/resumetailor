# ResumeTailor browser extension

1. Start ResumeTailor on `127.0.0.1` (port 8000–8010, or set another port in the
   extension options).
2. Download `resumetailor-extension-<version>.zip` from the latest GitHub release and
   unzip it (or use this `extension/` folder from a checkout).
3. Open `chrome://extensions` or `edge://extensions`, turn on **Developer mode**, choose
   **Load unpacked**, and select that folder.
4. In ResumeTailor, open **Settings → Browser** and choose **Pair a browser**.
5. Open the extension popup, enter the six-digit code, and choose **Pair**.

## Capturing jobs

- **Send to ResumeTailor** (popup), **Alt+Shift+S** (change it at
  `chrome://extensions/shortcuts`), or right-click **Send this page to ResumeTailor**.
  Shortcut and menu captures show a notification. In the options, "After a capture" can
  also start tailoring.
- **Tailor now** prepares it. **Fill this page** prepares an untracked job and starts Fill
  when it is ready, even if the popup closes. It never enables automatic submission.
  Fill uses ResumeTailor's configured browser; check the form and submit it yourself.
- LinkedIn, Indeed, Handshake, and Workday are assist-only. LinkedIn **Easy Apply** and
  Indeed's own **Apply now** form cannot be filled; Tailor still works.
- The popup only offers job actions on job pages. A capture that matches a job you
  already track links to it; a job your filters screen out says why.

## LinkedIn and Indeed

- **Save cards:** on a search page the popup lists the visible job cards with their
  queue status. Tick the ones you want and save them. They appear in the app under
  **Needs description**, and nothing is fetched from LinkedIn or Indeed by the app.
- **Allow on LinkedIn and Indeed** (popup or options) lets a small content script run on
  those sites. It shows a chip on job pages ("Save to ResumeTailor" or "✓ In queue ·
  status", with Tailor and Open in app), and when you open a job you saved, it sends
  that job's description so the saved entry is complete. Both can be turned off in the
  options.
- **Apply on the company site:** click Apply on the board, then capture the employer's
  page. It is attached to the job you already track instead of creating a second one.
- The extension never clicks, scrolls, navigates or opens pages by itself.

All LinkedIn/Indeed selectors live in `lib/sites.js`, with fallbacks. When a site
changes its markup, add the new selector first in that list.

## Fill the selected tab through the relay

The normal CDP browser mode remains the default. For the optional relay, run the app
and relay on the same host and with the same `RESUME_TAILOR_DATA_DIR`. After pairing:

1. In the extension options, open **Advanced** and turn on **Fill relay**. The browser
   asks for the `debugger` permission only now; turning the relay off removes it.
2. Start `python -m resume_tailor.apply.cdp_relay` in a separate terminal. It prints a
   one-time `ws://127.0.0.1:8011/cdp/...` URL.
3. Start ResumeTailor with `BROWSER_MODE=extension` and `EXTENSION_CDP_URL` set to that
   exact URL. Restarting the relay creates a new URL, so restart the app with it.
4. On the job tab, open **Advanced** in the popup and choose **Use this tab for Fill
   (relay)**, then use **Fill this page**. Keep that tab open; opening DevTools detaches
   it. The app leaves the filled form for your review and submission.

The relay binds only to `127.0.0.1:8011`. Its CDP URL contains a temporary secret.
The relay reuses that tab when Fill requests a new page. Only one tab can be attached
at a time; detach by closing the tab or stopping the relay. This mode was checked on
a synthetic Greenhouse-like page in Edge, not live job sites.

If a page shows a login wall or its job description is hidden in a cross-origin iCIMS
iframe, select the description and use **Send selection to ResumeTailor** from the
context menu. You can also open an iframe's job URL as its own tab and capture there.

## Privacy

The extension talks only to `127.0.0.1` (ports 8000–8010 or your configured port) and,
when enabled, the relay on port 8011. Opening the popup sends the current page URL to
the local app for lookup; with LinkedIn/Indeed allowed, the job you open there is looked
up too. Description text is sent only after you use a capture command, or when you open
a job you saved. The extension does not fetch external job sites and does not receive
your resume or model keys. Pairing tokens stay in extension local storage; revoke a
browser from Settings to invalidate its token. Full policy: `store/PRIVACY.md`.

## Development

```
npm ci        # once: jsdom for the page-parsing tests
npm test      # node --test tests/*.test.js
python generate_icons.py              # redraw icons/
python build_zip.py --version 1.2.3   # the release zip (release.yml does this per tag)
```

Store submission material (listing, privacy policy, permission justifications, steps)
is in `store/`.
