# ResumeTailor browser extension: privacy policy

_Last updated: 2026-09-29_

The ResumeTailor extension connects your browser to the ResumeTailor app running on
your own computer. It has no server of its own and does not send data to the
extension's developers or to anyone else.

## What the extension reads

- **The job page you capture.** When you choose **Send to ResumeTailor** (popup,
  right-click menu, keyboard shortcut or the page chip), the extension reads that tab's
  job title, company, location, description text and apply link.
- **Job cards you choose to save.** On a LinkedIn or Indeed search page, **Save cards**
  reads the visible cards' titles, companies, locations and job links, and saves only
  the cards you tick.
- **The job you open on LinkedIn or Indeed**, only if you allowed those sites in the
  extension options. The extension checks whether that job is already in your
  ResumeTailor queue. If it is a job you saved from search results, the extension
  sends its description so the saved entry is complete.
- **The current tab's address when you open the popup**, so the popup can show whether
  that job is already tracked.

The extension never clicks, scrolls, opens or fetches pages by itself.

## Where the data goes

Everything above is sent only to the ResumeTailor app on `127.0.0.1` (ports
8000–8010, or the port you set in the options). If you turn on the optional Fill relay,
the tab you attach is also connected to a local relay on `127.0.0.1:8011`. Nothing is
sent anywhere else.

## What the extension stores

In the browser's extension storage: the pairing token issued by your app, the app's
port, and your extension options. It does not store job pages or your resume.
Revoking the browser in ResumeTailor (**Settings → Browser**) invalidates the token;
removing the extension deletes everything it stored.

## What the extension does not do

- It does not collect analytics, crash reports or usage data.
- It does not sell, share or transfer data to third parties.
- It does not use data for advertising, credit or lending decisions.
- It does not read your resume, API keys or passwords.

## Contact

Questions: open an issue at https://github.com/jaydentrannnn/resumetailor/issues.
