# Submitting to the Chrome Web Store and Edge Add-ons

The owner submits by hand. Each release attaches `resumetailor-extension-<version>.zip`
(built by `.github/workflows/release.yml`, excluding `tests/`, `node_modules/` and this
`store/` folder). Upload that zip to both stores.

## Before each submission

1. Confirm `extension/manifest.json` `version` matches the release tag (the release
   workflow stamps it; `tests/test_extension_manifest.py` checks the repo copy).
2. Load the zip unpacked in a clean profile and walk through the live checklist in
   `docs/GUIDE.md` (pairing, capture, Save cards, chip, shortcut, options, relay).
3. Publish `store/PRIVACY.md` at a public URL (for example the repo's GitHub page for
   that file) — both stores require a privacy policy link.

## Chrome Web Store

1. Register at https://chrome.google.com/webstore/devconsole (one-time fee).
2. **Items → New item** → upload the zip.
3. **Store listing**: paste `LISTING.md` (name, short and detailed description,
   category), upload the screenshots and the 440×280 promo tile.
4. **Privacy practices**: single purpose and each permission justification from
   `PERMISSIONS.md`; data usage disclosures as listed there; privacy policy URL.
5. **Distribution**: Public (or Unlisted while testing).
6. Submit for review. Host permissions requested at runtime
   (`optional_host_permissions`) usually avoid the extended "broad host" review.

Updates: bump the version (new tag), upload the new zip on the same item.

## Microsoft Edge Add-ons

1. Register at https://partner.microsoft.com/dashboard/microsoftedge (free).
2. **Create new extension** → upload the same zip.
3. **Properties**: category Productivity, privacy policy URL, website URL (repo).
4. **Store listings** (English): description from `LISTING.md`, 300×300 logo,
   screenshots.
5. **Submit**, with the notes for certification from `PERMISSIONS.md` ("Optional"
   section) so the reviewer knows why `debugger` and LinkedIn/Indeed are requested.

## After approval

Put the store URLs in `frontend/src/pages/settings/BrowserSection.tsx`
(`STORE_LINKS`), so Settings → Browser offers them instead of the manual install.
