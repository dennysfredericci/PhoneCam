"""Feeds the OBS Virtual Camera at a constant 1920x1080 @ 30 fps.

The phone's frame rate jitters (Wi-Fi, encoder), but call apps expect a
steady camera. So the WebRTC side only drops its newest decoded frame into
``submit()``, and a dedicated thread re-sends whatever is newest at exactly
30 fps. When no phone is connected it sends black.
"""

import logging
import threading
import time

import av
import numpy as np
import pyvirtualcam

log = logging.getLogger(__name__)

WIDTH, HEIGHT, FPS = 1920, 1080, 30

OBS_HELP = (
    "The OBS Virtual Camera is not available.\n"
    "To fix it:\n"
    "  1. Install OBS Studio 30 or newer from https://obsproject.com\n"
    "  2. Open OBS, click 'Start Virtual Camera' once, then 'Stop Virtual Camera'.\n"
    "  3. If macOS asks, allow the extension in System Settings > General >\n"
    "     Login Items & Extensions > Camera Extensions.\n"
    "  4. Make sure OBS's own Virtual Camera is stopped, then start PhoneCam again."
)


class VirtualCameraError(RuntimeError):
    pass


class VirtualCamera:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame: av.VideoFrame | None = None
        self._seq = 0  # bumped on every submit so the thread knows to redraw
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._cam: pyvirtualcam.Camera | None = None
        self.device = ""
        self.error = ""

    def start(self) -> None:
        try:
            # pyvirtualcam converts RGB to the extension's native UYVY in C;
            # measured ~4 ms/frame, well within the 33 ms budget.
            self._cam = pyvirtualcam.Camera(WIDTH, HEIGHT, FPS, fmt=pyvirtualcam.PixelFormat.RGB, backend="obs")
        except Exception as exc:  # pyvirtualcam raises plain RuntimeError
            self.error = f"{OBS_HELP}\n\n(details: {exc})"
            raise VirtualCameraError(self.error) from exc
        self.device = self._cam.device
        log.info("Virtual camera started: %s %dx%d@%d", self.device, WIDTH, HEIGHT, FPS)
        self._thread = threading.Thread(target=self._run, name="vcam", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._cam:
            self._cam.close()
            self._cam = None

    def submit(self, frame: av.VideoFrame | None) -> None:
        """Called from the asyncio side with each decoded frame; None = show black."""
        with self._lock:
            self._frame = frame
            self._seq += 1

    def _run(self) -> None:
        canvas = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        drawn_seq = -1
        try:
            while not self._stop.is_set():
                with self._lock:
                    frame, seq = self._frame, self._seq
                if seq != drawn_seq:
                    drawn_seq = seq
                    _draw(canvas, frame)
                self._cam.send(canvas)  # copies the data, so reusing canvas is safe
                self._cam.sleep_until_next_frame()
        except Exception as exc:
            self.error = f"Virtual camera stopped unexpectedly: {exc}"
            log.exception("Virtual camera thread failed")


def _draw(canvas: np.ndarray, frame: av.VideoFrame | None) -> None:
    """Fit the frame into the canvas, keeping aspect ratio (black bars, no stretching)."""
    canvas[:] = 0
    if frame is None:
        return
    scale = min(WIDTH / frame.width, HEIGHT / frame.height)
    # Even sizes keep the YUV->RGB scaler happy (chroma is subsampled 2x).
    w = min(WIDTH, round(frame.width * scale / 2) * 2)
    h = min(HEIGHT, round(frame.height * scale / 2) * 2)
    img = frame.reformat(width=w, height=h, format="rgb24").to_ndarray()
    x, y = (WIDTH - w) // 2, (HEIGHT - h) // 2
    canvas[y : y + h, x : x + w] = img


def run_test_pattern(vcam: VirtualCamera, stop: threading.Event) -> None:
    """Moving test pattern that alternates landscape/portrait every 5 s.

    Lets you check the virtual camera (and the black-bar fitting) without a phone.
    """
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255)]
    start = time.monotonic()
    while not stop.is_set():
        t = time.monotonic() - start
        portrait = int(t // 5) % 2 == 1
        w, h = (720, 1280) if portrait else (1280, 720)
        img = np.zeros((h, w, 3), np.uint8)
        for i, color in enumerate(bars):
            img[:, i * w // len(bars) : (i + 1) * w // len(bars)] = color
        # A black square sliding left to right shows that frames are moving.
        size = w // 8
        x = int((t * w / 3) % (w - size))
        img[h // 2 - size // 2 : h // 2 + size // 2, x : x + size] = 0
        vcam.submit(av.VideoFrame.from_ndarray(img, format="rgb24"))
        stop.wait(1 / FPS)
