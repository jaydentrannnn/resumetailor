# PyInstaller spec for the desktop sidecar (plan Phase 5, DK2).
#
# Build from the repo root, after `npm run build` in frontend/:
#
#     pyinstaller desktop/sidecar/resumetailor.spec --noconfirm \
#         --distpath desktop/sidecar/dist --workpath build/pyinstaller
#
# Output: desktop/sidecar/dist/resumetailor-server/ (one folder, not one file: a onefile
# build unpacks itself on every launch, which makes the window wait). The Tauri bundle
# ships that folder as a resource (`src-tauri/tauri.conf.json`).
#
# Bundled: the app package with its data files (filler scripts, vocabulary seeds,
# watchlists, SQL schema), the built SPA, python-docx/docxtpl templates, and the
# Playwright client with its Node driver. No browser is bundled: fills drive the
# student's own browser over CDP or the extension relay.

import json
import os
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 - defined by PyInstaller
SPA = ROOT / "frontend" / "dist"
if not (SPA / "index.html").is_file():
    raise SystemExit(f"Build the frontend first: {SPA} has no index.html")

datas = [(str(SPA), "frontend/dist")]
binaries = []
hiddenimports = collect_submodules("resume_tailor") + collect_submodules("uvicorn")
datas += collect_data_files("resume_tailor")
for package in ("docx", "docxtpl", "pdfplumber", "pypdfium2", "litellm", "tiktoken"):
    datas += collect_data_files(package)
# LiteLLM loads cl100k_base lazily. Tiktoken discovers its encoding plugins at
# runtime, so static import analysis misses both the plugin and its load helper.
hiddenimports += collect_submodules("tiktoken") + collect_submodules("tiktoken_ext")
hiddenimports += collect_submodules("google.auth") + collect_submodules("google.oauth2")
hiddenimports += collect_submodules("google_auth_oauthlib")
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
hiddenimports += collect_submodules("litellm.llms.vertex_ai")
hiddenimports += collect_submodules("litellm.llms.anthropic")
# Installed-app client configuration is supplied by the release owner, never user tokens.
client_id = os.environ.get("RESUME_TAILOR_GOOGLE_CLIENT_ID", "")
client_secret = os.environ.get("RESUME_TAILOR_GOOGLE_CLIENT_SECRET", "")
if client_id and client_secret:
    # Keep installed-app configuration out of stageable repository folders.
    oauth_temp = tempfile.TemporaryDirectory(prefix="resumetailor-oauth-")
    oauth_config = Path(oauth_temp.name) / "vertex_oauth_client.json"
    oauth_config.write_text(
        json.dumps({"client_id": client_id, "client_secret": client_secret}), "utf-8",
    )
    datas.append((str(oauth_config), "resume_tailor/infra"))
for package in ("playwright",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "sidecar" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="resumetailor-server",
    console=True,  # stdout carries the READY line; the shell hides the console window
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="resumetailor-server",
    upx=False,
)
