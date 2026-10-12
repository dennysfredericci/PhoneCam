"""`--self-test`: prove the (packaged) app's libraries really work, then exit.

build.sh and CI run this inside the built PhoneCam.app, where a missing
native library or data file would otherwise only show up on a user's Mac.
It exercises every native piece without needing OBS or a phone: FFmpeg
H.264 encode/decode (PyAV), DTLS/SRTP (cryptography, pyOpenSSL, pylibsrtp),
the HTTPS server, the TURN relay port, and pyvirtualcam's native backend
(loaded, not opened: CI machines have no OBS).
"""

import asyncio
import socket
import sys
import time


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CountingCamera:
    """Stands in for VirtualCamera: counts the frames the server delivers."""

    def __init__(self) -> None:
        self.frames = 0
        self.size = None

    def submit(self, frame) -> None:
        if frame is not None:
            self.frames += 1
            self.size = (frame.width, frame.height)


async def _webrtc_loopback() -> str:
    import aiohttp
    import av
    import numpy as np
    from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

    from phonecam.server import PhoneCamServer

    class Pattern(VideoStreamTrack):
        async def recv(self):
            pts, time_base = await self.next_timestamp()
            frame = av.VideoFrame.from_ndarray(np.full((720, 1280, 3), pts % 255, np.uint8), format="rgb24")
            frame.pts, frame.time_base = pts, time_base
            return frame

    camera = _CountingCamera()
    server = PhoneCamServer(camera, _free_port(), _free_port(), pin="000000")
    await server.start()
    pc = RTCPeerConnection()
    try:
        base = f"https://127.0.0.1:{server.port}"
        headers = {"X-PhoneCam-PIN": "000000"}
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as http:
            async with http.get(f"{base}/") as r:
                assert r.status == 200 and "PhoneCam" in await r.text(), "phone page not served"
            async with http.get(f"{base}/config", headers=headers) as r:
                assert r.status == 200 and (await r.json())["iceServers"], "TURN relay not configured"
            pc.addTransceiver(Pattern(), direction="sendonly")
            await pc.setLocalDescription(await pc.createOffer())
            offer = {"sdp": pc.localDescription.sdp, "type": "offer", "clientId": "self-test"}
            async with http.post(f"{base}/offer", json=offer, headers=headers) as r:
                assert r.status == 200, f"offer rejected: {r.status}"
                answer = await r.json()
        await pc.setRemoteDescription(RTCSessionDescription(**answer))
        assert "H264" in answer["sdp"], "H.264 not negotiated"
        deadline = time.monotonic() + 15
        while camera.frames < 30 and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert camera.frames >= 30, f"only {camera.frames} frames received"
        return f"{camera.frames} frames of {camera.size[0]}x{camera.size[1]} received over WebRTC/H.264"
    finally:
        await pc.close()
        await server.stop()


def run_self_test() -> int:
    checks = []
    try:
        import pyvirtualcam  # noqa: F401  (loads the native OBS backends)

        checks.append("pyvirtualcam native backend loaded")
        import av

        av.CodecContext.create("h264", "r")
        checks.append(f"FFmpeg {av.ffmpeg_version_info} with H.264 decoder")
        import qrcode  # noqa: F401
        import rumps  # noqa: F401

        checks.append("menu bar libraries loaded")
        from phonecam.paths import resource_path

        assert resource_path("web", "index.html").is_file(), "web/index.html missing from bundle"
        checks.append("phone page bundled")
        checks.append(asyncio.run(_webrtc_loopback()))
    except Exception as exc:
        for line in checks:
            print(f"ok   {line}")
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for line in checks:
        print(f"ok   {line}")
    print("Self-test passed.")
    return 0
