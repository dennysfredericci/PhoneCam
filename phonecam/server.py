"""HTTPS server: serves the phone page and does WebRTC signaling with aiortc.

Signaling is a single HTTP round trip: the phone POSTs its SDP offer to
/offer and gets our SDP answer back. aiortc doesn't do "trickle ICE", so
both sides gather all their network candidates before sending the SDP. No
public STUN/TURN servers are used. The phone gets our own TURN-over-TCP relay
(turn.py) from GET /config, as a fallback for when UDP can't reach the Mac.

Only one phone is active at a time: a new offer closes the previous peer.
"""

import asyncio
import hmac
import logging
import re
import ssl
import time

from aiohttp import web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpReceiver, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

from .certs import ensure_certificate, local_ips
from .paths import resource_path
from .turn import TurnServer
from .vcam import VirtualCamera

log = logging.getLogger(__name__)

# If no frame arrives for this long (phone locked, Wi-Fi dropped), show black
# while ICE decides whether the connection is really gone.
STALL_TIMEOUT = 3.0
IP_CHECK_INTERVAL = 10.0
# Wrong-PIN protection: after this many wrong tries an address is locked out
# for PIN_LOCKOUT seconds, which makes guessing a 6-digit PIN impractical.
MAX_PIN_FAILURES = 5
PIN_LOCKOUT = 60.0


def _candidates(sdp: str) -> str:
    """Compact list of ICE candidates ("udp 192.168.1.5:5000 host") for the log.

    When the page loads but video never connects, these show which network
    addresses each side offered, which is usually where the problem is.
    """
    found = []
    for line in sdp.splitlines():
        if line.startswith("a=candidate:"):
            f = line.split()
            # a=candidate:<foundation> <component> <transport> <priority> <ip> <port> typ <type> ...
            found.append(f"{f[2].lower()} {f[4]}:{f[5]} {f[7]}")
    return ", ".join(found) or "none"


def _add_video_receiver(pc: RTCPeerConnection) -> None:
    """Pre-create the receiving transceiver with H.264 first, VP8 as fallback.

    aiortc negotiates codecs inside setRemoteDescription(), reusing an existing
    unassigned transceiver if there is one, so preferences must be set before.
    H.264 matters because phones encode it in hardware.
    """
    codecs = RTCRtpReceiver.getCapabilities("video").codecs
    order = {"video/H264": 0, "video/VP8": 1, "video/rtx": 2}
    codecs = sorted(codecs, key=lambda c: order.get(c.mimeType, 3))
    pc.addTransceiver("video", direction="recvonly").setCodecPreferences(codecs)


def _tune_answer_sdp(sdp: str) -> str:
    """Adjust the H.264 parameters in our SDP answer before the phone sees them.

    1. Advertise level 5.1 instead of aiortc's hard-coded 3.1. The
       profile-level-id in our answer tells the phone what we can *decode*;
       level 3.1 formally caps the stream at 1280x720 and some hardware
       encoders honour that. FFmpeg (aiortc's decoder) handles any level, so
       5.1 is truthful and leaves room for 1080p and 4:3 sensors (1920x1440).
       Only the level byte changes; the profile (constrained baseline) stays.
    2. aiortc only supports REMB congestion control, with which the phone's
       encoder starts at ~300 kbps and ramps up slowly. x-google-start-bitrate
       (kbps, honoured by Chrome and Safari's libwebrtc) makes it start sharp.
    """
    sdp = re.sub(r"profile-level-id=(42[0-9a-f]{2})1f", r"profile-level-id=\g<1>33", sdp, flags=re.I)
    return re.sub(r"^(a=fmtp:\d+ .*packetization-mode=1.*?)(\r?)$", r"\1;x-google-start-bitrate=4000\2", sdp, flags=re.M)


class PhoneCamServer:
    def __init__(self, vcam: VirtualCamera, port: int, turn_port: int, pin: str = "") -> None:
        self.vcam = vcam
        self.port = port
        self.pin = pin  # "" = no PIN required
        self._pin_failures: dict[str, tuple[int, float]] = {}  # ip -> (wrong tries, locked until)
        # The relay may only forward to this Mac's own addresses (see turn.py).
        self.turn: TurnServer | None = TurnServer(turn_port, allowed_peer=lambda ip: ip in self.ips or ip == "127.0.0.1")
        self.ips: list[str] = []
        self.pc: RTCPeerConnection | None = None
        self.client_id = ""  # random id sent by the phone page that owns self.pc
        self.status = "Waiting for phone"  # read by the CLI/menu bar
        self._ssl = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        self._runner: web.AppRunner | None = None
        self._ip_task: asyncio.Task | None = None

    @property
    def urls(self) -> list[str]:
        return [f"https://{ip}:{self.port}" for ip in self.ips]

    async def start(self) -> None:
        self._load_certificate(local_ips())
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/config", self._config)
        app.router.add_post("/offer", self._offer)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", self.port, ssl_context=self._ssl).start()
        log.info("HTTPS server listening on port %d", self.port)
        try:
            await self.turn.start()
        except OSError as exc:
            # Not fatal: direct Wi-Fi connections still work without the relay.
            log.warning("TURN relay disabled, cannot listen on port %d: %s", self.turn.port, exc.strerror)
            self.turn = None
        self._ip_task = asyncio.create_task(self._watch_ips())

    async def stop(self) -> None:
        if self._ip_task:
            self._ip_task.cancel()
        await self._close_peer()
        if self.turn:
            await self.turn.stop()
        if self._runner:
            await self._runner.cleanup()

    def _load_certificate(self, ips: list[str]) -> None:
        self.ips = ips
        cert, key = ensure_certificate(ips)
        # Reloading into the live context applies to every new TLS handshake,
        # so an IP change doesn't need a server restart.
        self._ssl.load_cert_chain(cert, key)

    async def _watch_ips(self) -> None:
        while True:
            await asyncio.sleep(IP_CHECK_INTERVAL)
            ips = local_ips()
            if ips != self.ips:
                log.info("Network changed, phone URL now: %s", ", ".join(f"https://{ip}:{self.port}" for ip in ips) or "none")
                self._load_certificate(ips)

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(resource_path("web", "index.html"), headers={"Cache-Control": "no-store"})

    def _check_pin(self, request: web.Request) -> web.Response | None:
        """None if the request carries the right PIN, else the error response to send.

        The page itself is public; the PIN guards /config (which hands out the
        relay credentials) and /offer (which starts streaming).
        """
        if not self.pin:
            return None
        ip = request.remote
        now = time.monotonic()
        failures, locked_until = self._pin_failures.get(ip, (0, 0.0))
        if now < locked_until:
            wait = int(locked_until - now) + 1
            return web.json_response({"error": f"Too many wrong PINs. Try again in {wait} seconds."}, status=429)
        given = request.headers.get("X-PhoneCam-PIN", "")
        if hmac.compare_digest(given.encode(), self.pin.encode()):  # constant-time compare
            self._pin_failures.pop(ip, None)
            return None
        if not given:
            return web.json_response({"error": "Enter the PIN shown on your Mac."}, status=401)
        failures += 1
        log.warning("Wrong PIN from %s (%d/%d)", ip, failures, MAX_PIN_FAILURES)
        if failures >= MAX_PIN_FAILURES:
            self._pin_failures[ip] = (0, now + PIN_LOCKOUT)
        else:
            self._pin_failures[ip] = (failures, 0.0)
        return web.json_response({"error": "Wrong PIN. Check the PIN shown on your Mac."}, status=401)

    async def _config(self, request: web.Request) -> web.Response:
        if denied := self._check_pin(request):
            return denied
        # Point the phone at our relay using the same host name it used to
        # load this page, which is by definition reachable from the phone.
        ice_servers = [self.turn.ice_server(request.url.host)] if self.turn else []
        return web.json_response({"iceServers": ice_servers}, headers={"Cache-Control": "no-store"})

    async def _offer(self, request: web.Request) -> web.Response:
        if denied := self._check_pin(request):
            return denied
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        client_id = str(params.get("clientId", ""))
        peer = request.remote

        # Tapping Start on a phone always takes over. An *automatic* reconnect
        # must not, otherwise a replaced phone would steal the camera back and
        # two phones would ping-pong forever.
        current = self.pc
        if (
            params.get("reconnect")
            and current is not None
            and client_id != self.client_id
            and current.connectionState in ("new", "connecting", "connected")
        ):
            log.info("Rejected automatic reconnect from %s: another phone is active", peer)
            return web.json_response({"error": "Another phone is using PhoneCam"}, status=409)

        log.info("Offer from %s", peer)
        await self._close_peer()  # a new phone (or a reconnect) replaces the old one
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.pc = pc
        self.client_id = client_id
        self.status = f"Connecting to {peer}"

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                asyncio.ensure_future(self._consume(pc, track))

        @pc.on("connectionstatechange")
        async def on_state():
            log.info("Peer %s: %s", peer, pc.connectionState)
            if pc is not self.pc:
                return
            self.status = {
                "connected": f"Connected to {peer}",
                "connecting": f"Connecting to {peer}",
                "disconnected": f"Connection to {peer} interrupted",
            }.get(pc.connectionState, "Waiting for phone")
            if pc.connectionState in ("failed", "closed"):
                await self._close_peer()

        log.info("Phone candidates: %s", _candidates(offer.sdp))
        _add_video_receiver(pc)
        try:
            await pc.setRemoteDescription(offer)
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)  # gathers all ICE candidates (no trickle)
        except Exception as exc:  # e.g. no codec in common
            log.exception("Negotiation with %s failed", peer)
            if pc is self.pc:
                await self._close_peer()
            return web.json_response({"error": f"Negotiation failed: {exc}"}, status=400)
        log.info("Mac candidates: %s", _candidates(pc.localDescription.sdp))
        return web.json_response({"type": pc.localDescription.type, "sdp": _tune_answer_sdp(pc.localDescription.sdp)})

    async def _consume(self, pc: RTCPeerConnection, track) -> None:
        """Forward decoded frames to the virtual camera while this peer is current."""
        logged_size = None
        try:
            while pc is self.pc:
                try:
                    frame = await asyncio.wait_for(track.recv(), STALL_TIMEOUT)
                except asyncio.TimeoutError:
                    self.vcam.submit(None)
                    continue
                if pc is not self.pc:
                    break
                if (frame.width, frame.height) != logged_size:
                    logged_size = (frame.width, frame.height)
                    log.info("Receiving %dx%d", *logged_size)
                self.vcam.submit(frame)
        except MediaStreamError:
            pass  # track ended: phone stopped or disconnected
        finally:
            if pc is self.pc:
                self.vcam.submit(None)

    async def _close_peer(self) -> None:
        pc, self.pc = self.pc, None
        self.vcam.submit(None)
        self.status = "Waiting for phone"
        if pc:
            await pc.close()
