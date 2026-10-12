"""Menu-bar app: what PhoneCam.app shows (status, phone URL, PIN, QR code, Quit).

Threads: AppKit's event loop must own the main thread, so the aiohttp/aiortc
server runs its own asyncio loop in a background thread. A 1-second timer on
the main thread reads the server's status and rebuilds the menu when it
changes. Reading those few attributes across threads is safe enough here:
they're replaced atomically and only displayed.
"""

import asyncio
import logging
import subprocess
import threading

import qrcode
import rumps
from AppKit import NSImage, NSPasteboard, NSPasteboardTypeString
from qrcode.image.pure import PyPNGImage

from phonecam.paths import support_dir
from phonecam.server import PhoneCamServer
from phonecam.vcam import VirtualCamera, VirtualCameraError

log = logging.getLogger(__name__)

QR_SIZE = 220  # points


class _ServerThread:
    """Runs PhoneCamServer on its own asyncio loop in a background thread."""

    def __init__(self, server: PhoneCamServer) -> None:
        self.server = server
        self.loop = asyncio.new_event_loop()
        self.error = ""
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="server", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(10)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.server.start())
        except OSError as exc:
            self.error = f"Port {self.server.port} is in use (is PhoneCam already running?)"
            log.error("Cannot start server: %s", exc)
            self._ready.set()
            return
        self._ready.set()
        self.loop.run_forever()

    def stop(self) -> None:
        if not self.loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop).result(timeout=5)
        except Exception:
            log.exception("Error while stopping the server")
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)


class PhoneCamApp(rumps.App):
    def __init__(self, port: int, turn_port: int, pin: str) -> None:
        super().__init__("PhoneCam", quit_button=None)
        self.pin = pin
        self.vcam = VirtualCamera()
        self.server = PhoneCamServer(self.vcam, port, turn_port, pin)
        self.server_thread = _ServerThread(self.server)
        self.camera_error = ""
        self._shown = None  # what the menu currently shows, to rebuild only on change
        self._set_icon("video")

    # ----- lifecycle -----

    def start(self) -> None:
        self._start_camera()
        self.server_thread.start()
        self._refresh()
        rumps.Timer(self._refresh, 1).start()
        self.run()

    def _start_camera(self) -> None:
        try:
            self.vcam.start()
            self.camera_error = ""
        except VirtualCameraError as exc:
            self.camera_error = str(exc)
            log.error("%s", exc)

    def _quit(self, _=None) -> None:
        self.server_thread.stop()
        self.vcam.stop()
        rumps.quit_application()

    # ----- menu -----

    def _status(self) -> tuple[str, str]:
        """(text, menu-bar symbol) for the current state."""
        if self.server_thread.error:
            return self.server_thread.error, "exclamationmark.triangle"
        if self.camera_error:
            return "OBS Virtual Camera not available", "exclamationmark.triangle"
        if self.vcam.error:
            return "Virtual camera stopped - quit and reopen PhoneCam", "exclamationmark.triangle"
        if self.server.connected:
            return self.server.status, "video.fill"
        return self.server.status, "video"

    def _refresh(self, _=None) -> None:
        status, symbol = self._status()
        state = (status, symbol, tuple(self.server.urls), bool(self.camera_error))
        if state == self._shown:
            return
        self._shown = state
        self._set_icon(symbol)

        items: list = [rumps.MenuItem(status)]  # items without a callback show greyed out
        if self.camera_error:
            items.append(rumps.MenuItem("How to Fix...", callback=self._show_camera_help))
            items.append(rumps.MenuItem("Try Again", callback=self._retry_camera))
        items.append(None)  # separator

        urls = self.server.urls
        if urls and not self.server_thread.error:
            items.append(rumps.MenuItem("Open on your phone (click to copy):"))
            for url in urls:
                items.append(rumps.MenuItem(f"    {url}", callback=lambda _, u=url: self._copy(u)))
            if self.pin:
                items.append(rumps.MenuItem(f"    PIN: {self.pin}", callback=lambda _: self._copy(self.pin)))
            items.append(self._qr_menu(urls))
        elif not self.server_thread.error:
            items.append(rumps.MenuItem("No network - connect to Wi-Fi"))

        items += [
            None,
            rumps.MenuItem('In Zoom/Teams/Meet/OBS, choose "OBS Virtual Camera"'),
            rumps.MenuItem("Open Log Folder", callback=lambda _: subprocess.run(["open", str(support_dir())])),
            None,
            rumps.MenuItem("Quit PhoneCam", callback=self._quit, key="q"),
        ]
        self.menu.clear()
        self.menu = items

    def _qr_menu(self, urls: list[str]) -> rumps.MenuItem:
        """'Show QR Code' submenu: one scannable code per URL, with the PIN built in.

        The PIN goes after '#', so the phone's browser keeps it locally (the
        page stores it) and never sends it over the network in the URL.
        """
        menu = rumps.MenuItem("Show QR Code")
        for i, url in enumerate(urls):
            target = f"{url}/#pin={self.pin}" if self.pin else url
            path = support_dir() / f"qr-{i}.png"
            qrcode.make(target, image_factory=PyPNGImage, box_size=10, border=2).save(str(path))
            if len(urls) > 1:
                menu.add(rumps.MenuItem(url))
            # rumps keys menu items by title, so each image item needs a distinct (blank) one.
            menu.add(rumps.MenuItem(" " * (i + 1), icon=str(path), dimensions=[QR_SIZE, QR_SIZE], template=False))
        return menu

    # ----- actions -----

    def _copy(self, text: str) -> None:
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(text, NSPasteboardTypeString)

    def _show_camera_help(self, _=None) -> None:
        rumps.alert(title="OBS Virtual Camera not available", message=self.camera_error)

    def _retry_camera(self, _=None) -> None:
        self._start_camera()
        self._refresh()

    def _set_icon(self, symbol: str) -> None:
        # A built-in SF Symbol (macOS 11+) as a template image, so it follows
        # light/dark menu bars. rumps (pinned 0.4.0) only takes image files,
        # so we set its NSImage attribute directly.
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, "PhoneCam")
        image.setTemplate_(True)
        self._icon_nsimage = image
        try:
            self._nsapp.setStatusBarIcon()
        except AttributeError:
            pass  # not running yet; rumps picks the image up at startup


def run_menubar(port: int, turn_port: int, pin: str) -> int:
    PhoneCamApp(port, turn_port, pin).start()
    return 0
