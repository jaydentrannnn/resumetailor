# ResumeTailor: owner's guide

What to do next, in order: clean up after the history rewrite, test the new code,
build an installer for yourself, move your data into the installed app, and keep it
updated. Commands are PowerShell on Windows unless a section says otherwise.

Contents:
0. [Do this first: the history rewrite](#0-do-this-first-the-history-rewrite)
1. [Two ways to run: dev checkout or installed app](#1-two-ways-to-run-dev-checkout-or-installed-app)
2. [Test the new code (dev checkout)](#2-test-the-new-code-dev-checkout)
3. [Build the installer](#3-build-the-installer)
4. [Install and first run](#4-install-and-first-run)
5. [Move your data into the app](#5-move-your-data-into-the-app)
6. [Updating: no reinstall needed](#6-updating-no-reinstall-needed)
7. [Day-to-day operation](#7-day-to-day-operation)
8. [Check these first on Windows](#8-check-these-first-on-windows)
9. [What is not done, and decisions left to you](#9-what-is-not-done-and-decisions-left-to-you)

---

## 0. Do this first: the history rewrite

All three branches (`main`, `extension`, `claude/dazzling-davinci-nlr8ob`) were
rewritten with `git filter-repo` and force-pushed (2026-09-25):

- **Replaced with synthetic values in every commit:** your legal name, street address,
  city, ZIP, phone number, old work email, school email and LinkedIn slug. The
  replacements are "Alex Jordan Lee Doe", "123 Main St", "Springfield", "12345",
  "555 010 0000" and `alex@example.com`.
- **Removed from every commit:** `projects.md`, your project write-ups.
- **Checked:** 106 commits scanned afterwards, with no matches in text or binary
  objects. The two branches whose latest version was already clean have
  byte-identical trees. The old and new `main` pass and fail the same tests.
- **Changed:** every commit hash. Branch names are unchanged.

**Every clone made before the rewrite still has the old history, including the personal
data.** That includes the Windows checkout and the orca workspace under
`C:\Users\Jayden Tran\orca\workspaces\ResumeTailor\`. For each one:

1. **Do not `git pull`, `git merge` or `git push` from it.** A pull merges the old history
   back in, and a push of any branch uploads it again.
2. Re-clone and carry over only the untracked files:

   ```powershell
   cd C:\path\to                      # the folder that holds your checkout
   Rename-Item resumetailor resumetailor-old
   git clone https://github.com/jaydentrannnn/resumetailor.git
   cd resumetailor
   git checkout claude/dazzling-davinci-nlr8ob
   robocopy ..\resumetailor-old\data data /E
   robocopy ..\resumetailor-old\templates templates /E
   robocopy ..\resumetailor-old\output output /E
   Copy-Item ..\resumetailor-old\.env .env
   ```

3. Once the new clone works (section 2), delete the old folder:
   `Remove-Item -Recurse -Force ..\resumetailor-old`. Its `.git` folder holds the old
   history. Do the same for the orca workspace. Let the other agent start from a fresh
   clone.
4. Add the extra patterns this rewrite covered to `data\pii_denylist.txt`: your city,
   school email address and LinkedIn slug. `tests/test_no_pii.py` then guards them too.

**On GitHub:**
- Old commits stay reachable by their exact hash until GitHub garbage-collects them.
  The repository is private, so only you can reach them.
- For a complete purge, ask GitHub Support to "remove cached views and run garbage
  collection" for `jaydentrannnn/resumetailor`. Say that the history was rewritten to
  remove personal data. The repo has no pull requests or forks, so nothing else holds
  the old commits.
- Commit *author* metadata still shows your school email on your own commits. That is
  normal. To hide it on future commits, turn on GitHub's "Keep my email address private"
  and run `git config --global user.email <id>+jaydentrannnn@users.noreply.github.com`.

**Bring `main` up to date.** `main` is 63 commits behind this branch, and this branch
builds directly on it. The **Run workflow** button in section 3 only appears for
workflows that are on the default branch. Open a pull request from
`claude/dazzling-davinci-nlr8ob` into `main` and merge it, or fast-forward it yourself:
`git push origin claude/dazzling-davinci-nlr8ob:main`.

---

## 1. Two ways to run: dev checkout or installed app

|                    | Dev checkout (`uvicorn`)                     | Installed app (ResumeTailor.exe)             |
|--------------------|----------------------------------------------|----------------------------------------------|
| Use it for         | changing code, tests, CLI (`tailor.py`), Docker, MCP for Claude Desktop, the extension relay | everyday tailoring and applying, the nightly run |
| Data               | repo `data\`, `templates\`, `output\`         | `%LOCALAPPDATA%\ResumeTailorData\{data,templates,output,cache}` |
| Settings file      | repo `.env`                                   | `%LOCALAPPDATA%\ResumeTailorData\.env` (optional) |
| API keys           | Windows Credential Manager, service "ResumeTailor" (shared by both); a key in `.env` wins | same |
| Port               | 8000 (whatever you pass)                      | first free of 8000–8010                      |
| Sign-in token      | off unless `RESUME_TAILOR_TOKEN` is set       | always on, new each launch (the window signs itself in) |
| Keeps running      | while the terminal is open                    | in the tray after you close the window       |
| Updates            | `git pull`                                    | install a newer installer over it (section 6) |

Rules:
- **Never run both at once on the same data folders.** The server must be the only
  process using a data folder: its locks and workspace switching are in-process.
- **Don't run both at once at all while using the browser extension.** It connects to
  the first ResumeTailor it finds on ports 8000–8010.
- **Test on a copy.** While you test the installed app, give it a *copy* of your data
  (section 5). A bug in a new build can then never damage your real data.

---

## 2. Test the new code (dev checkout)

### 2.1 Setup (once, in the fresh clone)

```powershell
& C:\ProgramData\anaconda3\python.exe -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.lock; pip install -e .
cd frontend; npm ci; npm run build; cd ..
```

If `npm run format:check` used to fail on about 190 files, that was Windows line endings,
not bad formatting. The new `frontend/.gitattributes` fixes it on a fresh clone.

### 2.2 Automated checks

```powershell
pytest                                                    # about 1950 tests, no network or Word needed
$env:RESUME_TAILOR_DATA_DIR = (New-Item -ItemType Directory "$env:TEMP\rt-empty-d" -Force).FullName
$env:RESUME_TAILOR_TEMPLATES_DIR = (New-Item -ItemType Directory "$env:TEMP\rt-empty-t" -Force).FullName
pytest                                                    # same suite with empty data folders
Remove-Item Env:RESUME_TAILOR_DATA_DIR, Env:RESUME_TAILOR_TEMPLATES_DIR

cd frontend
npm run lint; npx tsc -b; npm run test; npm run format:check
npx playwright install chromium                           # once
$env:E2E_PYTHON = "..\.venv\Scripts\python.exe"; npm run e2e   # browser end-to-end on a fake model
cd ..\extension; npm test; cd ..
pytest -m owner                                           # the tests that use your real master_resume.json
```

On the latest branch the suite gives **1944 passed, 24 skipped** on Linux. CI runs
the same checks on Windows, macOS and Linux when you push or open a pull request.

### 2.3 Run it

```powershell
uvicorn resume_tailor.web.app:app --app-dir src           # open http://127.0.0.1:8000
```

To try the sign-in gate, add `RESUME_TAILOR_TOKEN=auto` to `.env`. The terminal then
prints an `open http://127.0.0.1:8000/?t=...` link, and requests without the token get
401.

### 2.4 Hands-on checklist

Tick these off in the running app. Each line says what to do and what should happen.

**Setup and safety**
- [ ] A new profile (the header menu's profile switcher, or an empty data folder) opens `/welcome`: pick
      your field, choose a model, then import a resume (.docx or PDF) or start from
      scratch.
- [ ] The header pill says "Ready" or "N setup steps left", and each step links to its fix.
- [ ] Settings → Models: paste an API key and use **Test**. The key is stored in Credential
      Manager and the page only ever says it is set.
- [ ] Settings → About → **Download diagnostics** gives a zip with logs. Your name, email
      and phone show as `[redacted]`.

**Tailor**
- [ ] Job description: **Paste text**, **From a link** (a Greenhouse or Lever URL), and
      **Upload a file** (PDF or .docx) each fill the box and detect the company and role.
- [ ] Run a tailor. A 6-step progress bar appears, then the headline "Matched X of Y
      required skills · 1 page".
- [ ] In the bullet review, edit one bullet and click **Update resume (no AI)**: the PDF
      updates without a model call. An edit that pushes the resume past one page is
      refused with "Over by N lines". **Reset to AI version** undoes your edits.
- [ ] Coverage gaps split into skills that are *missing* and skills you have but haven't
      *tagged*.
- [ ] Run history: search, open an old run, and compare two runs.

**Profile, editor, template**
- [ ] Profile has one sticky **Save changes** bar across its tabs. Typing an invalid
      email or phone shows an inline error.
- [ ] Profile → Application: the visa status fills in the sponsorship defaults. Upload a
      transcript (Education) and a portfolio PDF (Saved answers and other preferences).
- [ ] Editor: add a section from a preset (Research, Leadership, Awards...). The bullet
      coach flags weak verbs and missing numbers. **Suggest tags** offers tags. History
      restores an earlier version.
- [ ] Template: a gallery of your saved templates plus the three built-in ones
      (classic, compact, business). Analyzer issues are in plain language. **Tune page
      fit** recalibrates.
- [ ] Import a PDF resume: it lands in a review step and is never saved on its own.

**Apply**
- [ ] Apply page tabs: **Needs you**, **In progress**, **Done**. Each "needs you" row says
      why, e.g. "Sign in to Workday" or "3 questions left blank".
- [ ] Settings drawer: sources (Simplify sections and a company watchlist), the
      auto-submit toggle (turning it on asks you to confirm), the caps, **Autofill
      model**, schedule plus **Run now**, and the browser card.
- [ ] **Pause all automation** in the header stops the queue and blocks any submit.
- [ ] Do a dry-run fill on a Greenhouse or Lever posting with auto-submit off:
  - it stops at review;
  - the phone is entered in international format;
  - a portfolio or work-sample upload field gets your portfolio PDF;
  - a multi-location checkbox list is answered from your location preference, or
    flagged for review;
  - after the resume upload, fields the site pre-filled wrongly are corrected, and the
    note says what the form had before.
- [ ] Workday always stops for review. LinkedIn, Indeed and Handshake are fill-only and
      never auto-submit.

**Browser extension**
- [ ] `edge://extensions` → Developer mode → **Load unpacked** → the repo's `extension\`
      folder.
- [ ] Settings → Browser → **Pair**, then type the 6-digit code in the extension popup.
- [ ] On a job posting: **Send to ResumeTailor** captures it, and a second send says
      "Already tracked". **Tailor now** starts tailoring.
- [ ] Revoke the pairing in Settings → Browser: the popup asks you to pair again.
- [ ] Optional relay mode, dev checkout only because it needs a separate Python process:
      follow `extension/README.md` → "Fill the selected tab through the relay".

The live checks the other agent could not do are LinkedIn and Greenhouse captures, the
badge count, revocation, and pause from the popup. They belong on this list, done in
your real Edge.

---

## 3. Build the installer

The result is an unsigned Windows installer: `ResumeTailor_<version>_x64-setup.exe`
(NSIS, per-user) and a `.msi` (per-machine). **Use the `-setup.exe`.** It needs no
admin rights, and installing newer versions over it is simplest.

### Option A: GitHub Actions (recommended; nothing to install)

1. Merge the branch into `main` (section 0).
2. GitHub → **Actions** → **Release** → **Run workflow** (branch `main`). Leave "Also build
   macOS" unticked unless you need a Mac build.
3. Wait about 20–30 minutes. Open the run → **Artifacts** → `installer-windows-x64` →
   unzip.

For a **versioned** build, tag it instead:

```powershell
git tag v0.1.0; git push origin v0.1.0
```

The installers then also appear on a **draft** release (Releases page), visible only to
you. The tag number becomes the installer version, so every later build must use a
higher tag (`v0.1.1`, `v0.2.0`, ...). Use plain numbers only: no `-beta` suffixes, which
the `.msi` format rejects.

**Cost:** private repos get 2,000 free Actions minutes a month. A Windows build counts
double (about 50–60 minutes). macOS counts ten times, which is why it is opt-in.
Repository variable `RELEASE_MACOS=true` turns macOS on for tag builds.

### Option B: build on your own PC

One-time prerequisites:
- **Rust**: install from https://rustup.rs (default MSVC toolchain).
- **Visual Studio Build Tools** with "Desktop development with C++".
- **Node 22** and **Python 3.13**. WebView2 already ships with Windows 11.

Then, from the repo root:

```powershell
.venv\Scripts\activate
pip install -r requirements.lock; pip install -e . pyinstaller
cd frontend; npm ci; npm run build; cd ..
pyinstaller desktop\sidecar\resumetailor.spec --noconfirm --distpath desktop\sidecar\dist --workpath build\pyinstaller
python desktop\sidecar\smoke.py desktop\sidecar\dist\resumetailor-server\resumetailor-server.exe
cd desktop
npx --yes @tauri-apps/cli@2 icon app-icon.svg
npx --yes @tauri-apps/cli@2 build --bundles nsis
```

The installer lands in `desktop\src-tauri\target\release\bundle\nsis\`. The smoke test
must print `sidecar OK ...` before you build the shell. The first Rust build takes about
10 minutes; later builds are faster. For a local build, set the version in
`desktop\src-tauri\tauri.conf.json` before building.

---

## 4. Install and first run

1. Run `ResumeTailor_..._x64-setup.exe`. Windows SmartScreen says "Windows protected your
   PC" because the installer is unsigned: click **More info** → **Run anyway**. It installs
   to `%LOCALAPPDATA%\ResumeTailor` and adds a Start menu entry.
2. Launch ResumeTailor. You see "Starting…" for a few seconds (longer the first time),
   then the app, already signed in.
3. **Closing the window hides it to the tray**, so the nightly run keeps going. Quit for
   real from the tray icon → **Quit**.
4. Settings: create `%LOCALAPPDATA%\ResumeTailorData\.env` if you use settings from your
   repo `.env`, such as the model, `OLLAMA_BASE_URL` or `RESUME_TAILOR_PDF_BACKEND`.
   Copying your repo `.env` there works. Then:
   - delete any `RESUME_TAILOR_*_DIR` lines, unless you deliberately want the app on
     other folders;
   - if it has `CHROME_CDP_URL=http://host.docker.internal:9222` (the Docker value),
     delete that line; the app defaults to `http://127.0.0.1:9222`.

   Restart the app after editing it.
5. Model: Ollama must be running on this PC, or add an API key in Settings → Models.
6. PDFs: Word does the conversion on Windows (Office must be installed). The fallback is
   LibreOffice plus `RESUME_TAILOR_PDF_BACKEND=soffice` in that `.env`.
7. Filling forms: start Edge with remote debugging, using the command on the Apply page's
   browser card (port 9222), or use the paired extension.
8. Logs: `%LOCALAPPDATA%\ResumeTailorData\output\logs\app.log`. If the app cannot start
   its server three times in a row, the window shows this folder.

---

## 5. Move your data into the app

**While testing:** give the app a copy. Quit the app (tray → Quit) and stop `uvicorn`,
then:

```powershell
$dst = "$env:LOCALAPPDATA\ResumeTailorData"
robocopy data      "$dst\data"      /E
robocopy templates "$dst\templates" /E
robocopy output    "$dst\output"    /E
```

Start the app and check that Profile, the resume editor, the Template page and the Apply
list look the way they did in dev.

**Things that need redoing after a move:**
- **Transcript and portfolio:** re-upload them in Profile → Application. The profile
  stores their full paths, which still point at the repo. Re-uploading also makes saved
  application kits rebuild before their next fill.
- **Applications prepared before the move** point their kits at the old `output\` folder.
  Keep the repo's `output\` until those are done, or run **Tailor files** on them again.
- **Page fit:** retune with **Tune page fit** if the app converts PDFs differently from
  your dev setup, for example Word in one and LibreOffice in the other.
- **Extension pairing** is stored in the data folder, so it moves with the copy. The
  extension finds the app's port by itself.

**Switching over for good:** do the copy again from your latest dev data, then stop using
the repo folders for daily work. Keep dev for code changes, on a throwaway or copied
data folder.

Alternative (not recommended long term): point the app at the repo folders by putting
`RESUME_TAILOR_DATA_DIR=C:\path\to\resumetailor\data` (and the `TEMPLATES`, `OUTPUT`
lines) in the app's `.env`. Then never run dev and the app at the same time.

---

## 6. Updating: no reinstall needed

- **Update by installing the newer `-setup.exe` over the current one.** Quit the app from
  the tray first. You don't need to uninstall. Your data is in `ResumeTailorData`, a
  separate folder, and the installer never touches it.
- There is **no auto-updater yet**: you build or download each new version (section 3)
  and run it. An in-app updater needs a signing key and an update manifest (section 9).
- **Version numbers:**
  - Tag builds get their version from the tag: always go up.
  - Builds from **Run workflow** without a tag all say `0.1.0`. The `-setup.exe`
    reinstalls over the same version without trouble; the `.msi` refuses. Another
    reason to use the `-setup.exe`.
- **Database upgrades** run automatically on the first start of a newer version. Don't
  go back to an older version afterwards: it refuses to open the data with "Please
  update the app".
- **Back up before a big update:** copy `%LOCALAPPDATA%\ResumeTailorData` somewhere. That
  one folder is everything, apart from API keys and the Workday password, which are in
  Credential Manager.
- **Uninstall:** Settings → Apps → ResumeTailor. Your `ResumeTailorData` folder stays.
  The uninstaller's "delete application data" box only clears the window's browser cache
  (`%LOCALAPPDATA%\app.resumetailor.desktop`).

---

## 7. Day-to-day operation

- **Nightly run:** Apply → settings drawer → Schedule.
  - The app must be running; the tray is enough.
  - If the PC was off at the scheduled time, it catches up on the next start within 12
    hours. After that it shows "Missed" with **Run now**.
  - A run discovers new postings, screens them, tailors the ones that pass, and fills
    them within your caps.
- **What needs you:** the **Needs you** tab. Typical items are sign-ins, emailed codes,
  CAPTCHAs, questions it wouldn't guess (legal and eligibility), and a final check
  before Workday submits.
- **Emergency stop:** **Pause all automation** in the header.
- **Auto-submit** is off until you turn it on. Even then it:
  - respects the per-run, per-day and per-company caps;
  - skips anything that looks like a duplicate;
  - spaces submits 20–90 seconds apart;
  - never auto-submits Workday, LinkedIn, Indeed or Handshake;
  - saves before and after screenshots of each submit.
- **Claude Desktop (MCP)** with the installed app: the app's token changes every launch.
  1. Put a fixed `RESUME_TAILOR_TOKEN=<long random string>` in
     `%LOCALAPPDATA%\ResumeTailorData\.env`.
  2. Give Claude Desktop's MCP config the same token as `RESUME_TAILOR_TOKEN`, plus
     `RESUME_TAILOR_API=http://127.0.0.1:8000`. Use 8000 as long as nothing else holds
     that port.
- **Problems:** Settings → About → **Download diagnostics**, and `app.log` (section 4).

---

## 8. Check these first on Windows

The installed app was built and tested on Linux here. The Windows installer has not run
yet. On your first install, check:

1. **The app starts.** "Starting…" turns into the app within about 15 seconds. If you get
   the failure screen instead, look at `app.log` in the folder it shows.
2. **PDF conversion through Word** works from the installed app: run one tailor. If it
   fails at the PDF step, use the LibreOffice fallback (section 4, step 6) and tell me.
   It would mean the build is missing a Word automation module.
3. **API keys:** a key saved in Settings → Models survives a restart. If the build can't
   reach Credential Manager, it falls back to an encrypted file in the data folder.
4. **Installing a template** works (the Template page). This was a real bug in the
   frozen build, fixed on 2026-09-25.
5. **The browser card** on the Apply page reaches Edge on 9222.
6. **Antivirus:** some antivirus tools flag unsigned PyInstaller programs. If yours
   quarantines `resumetailor-server.exe`, allow it; signing (section 9) avoids this.

---

## 9. What is not done, and decisions left to you

**Not built, from the desktop plan:**
- auto-updater;
- code signing (Windows) and notarization (macOS);
- tray items Pause, Run discovery and launch-at-login (the tray has Open and Quit only);
- a "Copy diagnostics" button on the failure screen (it shows the log folder instead);
- LibreOffice detection and font installation (DK5);
- importing an old data folder from inside the app (DK6; section 5 is the manual
  version);
- publishing the extension to the Chrome and Edge stores (DK8);
- an Intel Mac build;
- testing on clean Windows and macOS machines.

**Other known limits:**
- The extension relay needs manual start and tab attach, supports one tab at a time,
  and works from dev only.
- Cross-origin iCIMS capture needs a text selection.
- iCIMS, Taleo, SuccessFactors and Oracle only recognise their screens; they don't do
  full fills yet.
- Stored transcript, portfolio and kit paths are absolute (section 5).

**Your decisions:**
1. **Merge into `main`** (section 0). Needed for **Run workflow**.
2. **Windows code-signing certificate** (roughly $100–400 a year). Removes the
   SmartScreen and antivirus warnings. Optional for personal use.
3. **Auto-updater:** I can add Tauri's updater. It needs a signing key pair (free) that
   you keep secret, and a published release feed.
4. **Apple Developer account** ($99 a year), only if you want a Mac build that opens
   without warnings.
5. **Extension store listing** (unlisted is fine), if you want to install it without
   developer mode.
