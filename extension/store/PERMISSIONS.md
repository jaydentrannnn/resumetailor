# Permission justifications

Paste these into the store forms ("Privacy practices" on the Chrome Web Store, the
"Permissions" notes on Edge Add-ons). `tests/extension/test_extension_manifest.py` checks that
every permission in `manifest.json` is listed here.

**Single purpose:** Send the job posting you are viewing to the ResumeTailor app
running on your own computer, so the app can tailor your resume to it.

## Required

- `storage`: Keeps the pairing token from the local app, the app's port and the
  user's options. Nothing is synced or sent elsewhere.
- `activeTab`: Reads the job page in the current tab only when the user asks to
  capture it (popup, keyboard shortcut or right-click menu).
- `scripting`: Runs the page reader in that tab to extract the job title, company,
  location, description and apply link, and lists the job cards on a search page
  when the user opens **Save cards**.
- `contextMenus`: Adds "Send this page / selection to ResumeTailor" to the right-click
  menu.
- `alarms`: Refreshes the toolbar badge (how many applications need the user) once a
  minute, and continues a "prepare then fill" request the user started after the popup
  closes.
- `notifications`: Confirms a capture started from the keyboard shortcut or the
  right-click menu, where no popup is open.
- `http://127.0.0.1/*`: The ResumeTailor app runs on the user's own computer; this is
  the only place the extension sends data.
- `http://localhost/*`: The same local app, for setups that address it as localhost.

## Optional (asked for at runtime)

- `https://www.linkedin.com/*`: Only after the user clicks **Allow on LinkedIn and
  Indeed**. On LinkedIn job pages it shows a small "Save to ResumeTailor" chip, and when
  the user opens a job they saved from search results it sends that job's description
  to the local app. It never clicks, scrolls, navigates or fetches pages.
- `https://*.indeed.com/*`: The same as LinkedIn, for Indeed's regional sites.
- `debugger`: Only when the user turns on **Fill relay** in the options. It lets the
  local app fill the application form in the one tab the user attaches, so the user
  can review and submit it themselves. It is never used on other tabs and is never
  requested otherwise.

## Remote code

None. All scripts ship inside the extension package.

## Data usage disclosures

- Collects: website content (job pages the user captures) and web history (the address
  of the page open when the popup is used). Both go only to the user's own computer.
- Not sold, not used for unrelated purposes, not used for creditworthiness or lending.
