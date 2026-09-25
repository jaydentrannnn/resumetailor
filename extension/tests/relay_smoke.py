"""Local, synthetic relay probe; run manually on extension-relay-spike only."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from playwright.async_api import async_playwright
from websockets.asyncio.client import connect

from resume_tailor import config, data
from resume_tailor.apply import fill, packet, store
from resume_tailor.apply import profile as profile_mod
from resume_tailor.apply.packet import Packet
from resume_tailor.apply.profile import ApplicantProfile
from resume_tailor.web import extension
from resume_tailor.web.schemas import ApplySettings

ROOT = Path(__file__).resolve().parents[2]
TEMP = ROOT / ".tmp-test" / "relay-smoke"
TEMP.mkdir(parents=True, exist_ok=True)
config.DATA_ROOT = TEMP / "data"
config.OUTPUT_DIR = TEMP / "output"
config.APPLICATIONS_OUTPUT_DIR = TEMP / "output" / "applications"
config.APPLICATIONS_PATH = TEMP / "data" / "applications.json"


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = (
            b"<html><h1>Analyst</h1><label>First Name<input id='first'></label>"
            b"<label>Last Name<input id='last'></label>"
            b"<label>Email<input id='email' type='email'></label>"
            b"<label>Resume<input id='upload' type='file'></label>"
            b"<button id='submit_app' type='submit'>Submit Application</button>"
            b"<iframe src='http://127.0.0.1:8766/frame'></iframe>"
            b"<script>setTimeout(()=>{const e=document.createElement('p');e.id='late';"
            b"e.textContent='ready';document.body.append(e)},400)</script></html>"
        )
        if self.path == "/frame":
            body = b"<html><input id='frame-field'></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


async def run() -> None:
    fixture = HTTPServer(("127.0.0.1", 8765), Fixture)
    frame_fixture = HTTPServer(("127.0.0.1", 8766), Fixture)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    threading.Thread(target=frame_fixture.serve_forever, daemon=True).start()
    token = extension.complete_pairing(extension.start_pairing()["code"])[1]
    env = dict(os.environ)
    env["RESUME_TAILOR_DATA_DIR"] = str(TEMP / "data")
    relay = subprocess.Popen(
        [str(ROOT / ".venv/Scripts/python.exe"), "-m", "resume_tailor.apply.cdp_relay"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    browser = None
    try:
        cdp_url = relay.stdout.readline().split("Relay CDP URL: ")[-1].strip()
        print("Relay started:", cdp_url.split("/cdp/")[0], flush=True)
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        browser = subprocess.Popen(
            [
                str(edge),
                "--headless=new",
                "--no-first-run",
                "--disable-gpu",
                "--remote-debugging-port=9223",
                f"--user-data-dir={TEMP / ('profile-' + str(int(time.time())))}",
                f"--disable-extensions-except={ROOT / 'extension'}",
                f"--load-extension={ROOT / 'extension'}",
                "http://127.0.0.1:8765/job",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        worker_url = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:9223/json/list", timeout=1
                ) as response:
                    targets = json.load(response)
                worker_url = next(
                    (
                        item["webSocketDebuggerUrl"]
                        for item in targets
                        if item["type"] == "service_worker"
                        and item["url"].endswith("background.js")
                    ),
                    None,
                )
                if worker_url and any(
                    item["type"] == "page" and "/job" in item["url"] for item in targets
                ):
                    break
            except Exception:
                pass
            await asyncio.sleep(0.2)
        if not worker_url:
            raise RuntimeError("Edge extension service worker did not start")
        extension_id = next(
            item["url"].split("/")[2]
            for item in targets
            if item["type"] == "service_worker" and item["url"].endswith("background.js")
        )
        popup_request = urllib.request.Request(
            f"http://127.0.0.1:9223/json/new?chrome-extension://{extension_id}/popup.html",
            method="PUT",
        )
        with urllib.request.urlopen(popup_request, timeout=3) as response:
            popup_target = json.load(response)
        async with connect(popup_target["webSocketDebuggerUrl"]) as worker:
            await worker.send(json.dumps({"id": 0, "method": "Runtime.enable"}))
            context_id = None
            enabled = False
            while True:
                event = json.loads(await asyncio.wait_for(worker.recv(), timeout=10))
                if event.get("method") == "Runtime.executionContextCreated":
                    context = event["params"]["context"]
                    if context.get("origin", "").startswith("chrome-extension://"):
                        context_id = context["id"]
                    print("Popup context:", context.get("origin"), flush=True)
                if event.get("method") == "Runtime.exceptionThrown":
                    print(
                        "Worker exception:",
                        event.get("params", {}).get("exceptionDetails", {}).get("text"),
                        flush=True,
                    )
                if event.get("id") == 0:
                    enabled = True
                if enabled and context_id is not None:
                    break
            expression = (
                "(async()=>{await chrome.storage.local.set({token:" + json.dumps(token) + "});"
                "const tabs=await chrome.tabs.query({});"
                "const tab=tabs.find(t=>t.id!==chrome.tabs.TAB_ID_NONE && "
                "!String(t.url).startsWith('chrome-extension:'));"
                "return await chrome.runtime.sendMessage({type:'relay',tab:{id:tab.id,url:'http://127.0.0.1:8765/job'}});})()"
            )
            await worker.send(
                json.dumps(
                    {
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": expression,
                            "contextId": context_id,
                            "awaitPromise": True,
                            "returnByValue": True,
                        },
                    }
                )
            )
            while True:
                reply = json.loads(await asyncio.wait_for(worker.recv(), timeout=15))
                if reply.get("id") == 1:
                    print(
                        "Attach result:",
                        reply.get("result", {}).get("result", {}).get("value"),
                        reply.get("result", {}).get("exceptionDetails"),
                        reply.get("error"),
                        flush=True,
                    )
                    break
        async with async_playwright() as playwright:
            connected = await playwright.chromium.connect_over_cdp(cdp_url, timeout=15_000)
            print("Playwright connected; contexts:", len(connected.contexts))
            results = {}
            for context in connected.contexts:
                for page in context.pages:
                    print("Page:", page.url)
                    print(
                        "Evaluate:",
                        await page.evaluate("document.querySelector('h1')?.textContent"),
                    )

                    async def probe(name, action):
                        try:
                            results[name] = await action()
                        except Exception as exc:
                            results[name] = (
                                f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0]}"
                            )

                    async def fill_fixture(page=page):
                        await page.locator("#first").fill("Ada")
                        await page.locator("#last").fill("Lovelace")
                        return await page.evaluate("[first.value,last.value].join(' ')")

                    async def upload_fixture(page=page):
                        synthetic = TEMP / "synthetic-cv.txt"
                        synthetic.write_text("Synthetic resume for relay test", encoding="utf-8")
                        await page.locator("#upload").set_input_files(str(synthetic))
                        return await page.evaluate("upload.files[0].text()")

                    async def frame_fixture_test(page=page):
                        await (
                            page.frame_locator("iframe")
                            .locator("#frame-field")
                            .wait_for(timeout=5_000)
                        )
                        frame = next(
                            item for item in page.frames if item.url.endswith(":8766/frame")
                        )
                        return await frame.evaluate("document.querySelector('#frame-field')?.id")

                    async def new_page(context=context):
                        created = await context.new_page()
                        return created.url

                    await probe("fill", fill_fixture)
                    await probe("upload", upload_fixture)
                    await probe("cross_origin_frame", frame_fixture_test)
                    await probe(
                        "wait_for",
                        lambda page=page: page.wait_for_selector("#late", timeout=5_000),
                    )
                    await probe("new_page", new_page)
                    print(
                        "Probe results:",
                        {key: str(value)[:180] for key, value in results.items()},
                        flush=True,
                    )
            await connected.close()
            if any(str(value).startswith("FAILED:") for value in results.values()):
                raise RuntimeError("One or more relay GO probes failed")
        os.environ["BROWSER_MODE"] = "extension"
        os.environ["EXTENSION_CDP_URL"] = cdp_url
        job_dir = config.OUTPUT_DIR / "jobs" / "relay-job"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "run.json").write_text('{"status":"succeeded"}', encoding="utf-8")
        (job_dir / "tailored.pdf").write_bytes(b"%PDF-1.4 synthetic resume")
        (job_dir / "expansion.json").write_text(
            '{"entries":[],"source_experience_count":0}', encoding="utf-8"
        )
        (job_dir / "jd.txt").write_text("Synthetic Greenhouse job", encoding="utf-8")
        store.upsert(
            store.Application(
                source="extension",
                source_job_id="relay-app",
                company="Acme",
                role="Analyst",
                ats="greenhouse",
                status="ready",
                job_id="relay-job",
                posting_url="http://127.0.0.1:8765/job",
                final_url="http://127.0.0.1:8765/job",
            )
        )
        packet.build_packet = lambda _job_id: Packet(
            job_id="relay-job",
            built_at="2026-09-25T00:00:00+00:00",
            ats="greenhouse",
            fields={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
            artifacts={"resume_pdf": str(job_dir / "tailored.pdf")},
        )
        profile_mod.load_profile = lambda: (ApplicantProfile(first_name="Ada"), False)
        data.load = lambda: SimpleNamespace(
            contact=SimpleNamespace(name="Ada Lovelace"), all_bullets=lambda: []
        )
        result = await asyncio.to_thread(
            fill.fill_application,
            "relay-app",
            settings=ApplySettings(cover_letter=False, auto_submit_enabled=False),
            submit_mode="awaiting_review",
            on_progress=lambda message: print("Fill progress:", message, flush=True),
        )
        print("Actual Fill:", result.status, result.error, flush=True)
        print("Persisted Fill:", store.get("relay-app").status, flush=True)
        assert result.status == "awaiting_review", result.error
        app = store.get("relay-app")
        app.status = "ready"
        store.upsert(app)

        def close_on_open(message: str) -> None:
            if not message.startswith("opening posting:"):
                return
            with urllib.request.urlopen("http://127.0.0.1:9223/json/list", timeout=3) as response:
                open_targets = json.load(response)
            target = next(
                item for item in open_targets if item["type"] == "page" and "/job" in item["url"]
            )
            with urllib.request.urlopen(
                f"http://127.0.0.1:9223/json/close/{target['id']}", timeout=3
            ):
                pass

        detached = await asyncio.to_thread(
            fill.fill_application,
            "relay-app",
            settings=ApplySettings(cover_letter=False, auto_submit_enabled=False),
            submit_mode="awaiting_review",
            on_progress=close_on_open,
        )
        print("Detached Fill:", detached.status, detached.error, flush=True)
        assert detached.status == "fill_failed"
        assert detached.error == "Tab was closed or DevTools opened"
    finally:
        if browser:
            browser.terminate()
            browser.wait(timeout=10)
        relay.terminate()
        relay.wait(timeout=10)
        fixture.shutdown()
        frame_fixture.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
