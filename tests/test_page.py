"""The real phone page (index.html) in headless Chrome with a fake camera.

Covers what the aiortc tests can't: the page's JavaScript, Chrome's H.264
encoder, the PIN from the QR link, and the TURN relay path.

Opt-in: these only run with PHONECAM_BROWSER_TESTS=1, which CI sets. On a
developer's Mac, launching Chrome can pop up macOS dialogs (for example
about the keychain), so a plain `pytest` never starts it.
"""

import asyncio
import itertools
import os
import subprocess
from pathlib import Path

import aiohttp
import pytest

from helpers import REAL_HOME, free_port, start_server, wait_for

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
# When asked for (CI), a missing Chrome is a failure, not a silent skip.
pytestmark = pytest.mark.skipif(os.environ.get("PHONECAM_BROWSER_TESTS") != "1", reason="set PHONECAM_BROWSER_TESTS=1 to run (CI does)")


class Browser:
    """Minimal Chrome DevTools Protocol client: just enough to evaluate JS."""

    def __init__(self, ws):
        self.ws = ws
        self.ids = itertools.count(1)

    async def eval(self, expression: str):
        msg_id = next(self.ids)
        await self.ws.send_json({"id": msg_id, "method": "Runtime.evaluate",
                                 "params": {"expression": expression, "awaitPromise": True, "returnByValue": True}})
        while True:
            msg = await self.ws.receive_json()
            if msg.get("id") == msg_id:
                return msg["result"].get("result", {}).get("value")


async def _open_page(url: str, profile: Path):
    port = free_port()
    chrome = subprocess.Popen([
        str(CHROME), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        "--use-fake-device-for-media-stream=fps=30", "--use-fake-ui-for-media-stream",
        "--ignore-certificate-errors", "--no-first-run", "--no-default-browser-check",
        # Never touch the macOS keychain: without this, Chrome asks the user
        # for one in a dialog (and blocks until it's answered).
        "--use-mock-keychain", "--password-store=basic",
        url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        # The tests' temporary HOME has no Library/Keychains; give Chrome the real one.
        env={**os.environ, "HOME": REAL_HOME})
    http = aiohttp.ClientSession()
    for _ in range(100):
        try:
            async with http.get(f"http://127.0.0.1:{port}/json") as r:
                pages = [p for p in await r.json() if p["type"] == "page"]
                if pages:
                    break
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(0.2)
    ws = await http.ws_connect(pages[0]["webSocketDebuggerUrl"], max_msg_size=0)
    return chrome, http, ws


@pytest.mark.parametrize("relay", [False, True], ids=["direct", "relay"])
def test_page_goes_live_with_pin_from_qr_link(relay, tmp_path):
    assert CHROME.exists(), f"PHONECAM_BROWSER_TESTS=1 but Chrome isn't installed at {CHROME}"

    async def scenario():
        server, camera = await start_server(pin="2468")
        query = "?relay" if relay else ""
        chrome, http, ws = await _open_page(f"https://127.0.0.1:{server.port}/{query}#pin=2468", tmp_path / "chrome")
        browser = Browser(ws)
        try:
            # Wait for the phone page itself (a cold Chrome starts on about:blank).
            for _ in range(100):
                if await browser.eval("location.protocol === 'https:' && document.readyState === 'complete'"):
                    break
                await asyncio.sleep(0.2)
            assert await browser.eval("location.hash") == "", "PIN should be removed from the address bar"
            assert await browser.eval("localStorage.getItem('phonecam-pin')") == "2468", "PIN from the QR link not stored"
            await browser.eval("document.getElementById('start').click()")

            async def page_state():
                return await browser.eval("document.getElementById('state').textContent + ' | ' + document.getElementById('stats').textContent")

            state = ""
            for _ in range(60):
                state = await page_state()
                if "Live on Mac" in state and "fps" in state:
                    break
                await asyncio.sleep(0.5)
            assert "Live on Mac" in state and "H264" in state, state
            assert ("via TCP relay" in state) == relay, state
            await wait_for(lambda: len(camera.frames) >= 30)
            assert camera.frames[-1] == (1920, 1080)
            await wait_for(lambda: "fps" in server.stats)
            assert ("via TCP relay" in server.stats) == relay, server.stats
        finally:
            await ws.close()
            await http.close()
            chrome.terminate()
            chrome.wait(10)
            await server.stop()

    asyncio.run(scenario())
