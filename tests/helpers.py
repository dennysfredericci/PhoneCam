"""Shared test helpers: a fake camera, a fake phone (aiortc) and small utilities."""

import asyncio
import os
import socket
import time

import aiohttp
import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

from phonecam.server import PhoneCamServer

# Read at import, before the isolated_home fixture swaps HOME for a temp folder.
REAL_HOME = os.environ["HOME"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeCamera:
    """Stands in for VirtualCamera and records what the server submits."""

    def __init__(self) -> None:
        self.frames: list[tuple[int, int]] = []
        self.blacks = 0

    def submit(self, frame) -> None:
        if frame is None:
            self.blacks += 1
        else:
            self.frames.append((frame.width, frame.height))


class Pattern(VideoStreamTrack):
    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self.width, self.height = width, height

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        img = np.full((self.height, self.width, 3), pts % 255, np.uint8)
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts, frame.time_base = pts, time_base
        return frame


async def start_server(pin: str = "") -> tuple[PhoneCamServer, FakeCamera]:
    camera = FakeCamera()
    server = PhoneCamServer(camera, free_port(), free_port(), pin)
    await server.start()
    return server, camera


def http_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))  # self-signed cert


async def phone_offer(http, server, client_id="A", reconnect=False, size=(640, 360), pin=""):
    """Act like the phone page: send an offer, apply the answer. Returns (pc, status, body)."""
    pc = RTCPeerConnection()
    pc.addTransceiver(Pattern(*size), direction="sendonly")
    await pc.setLocalDescription(await pc.createOffer())
    offer = {"sdp": pc.localDescription.sdp, "type": "offer", "clientId": client_id, "reconnect": reconnect}
    url = f"https://127.0.0.1:{server.port}/offer"
    async with http.post(url, json=offer, headers={"X-PhoneCam-PIN": pin}) as response:
        status, body = response.status, await response.json()
    if status == 200:
        await pc.setRemoteDescription(RTCSessionDescription(**body))
    else:
        await pc.close()
    return pc, status, body


async def wait_for(condition, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for condition")
        await asyncio.sleep(0.1)
