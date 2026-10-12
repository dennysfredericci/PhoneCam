"""Minimal TURN relay over TCP, so video still flows when UDP can't reach the Mac.

Why: WebRTC media normally goes over UDP directly between phone and Mac.
That fails when the iPhone *is* the network (Personal Hotspot over Wi-Fi or
USB: Safari only offers its mobile-data address), and over `adb reverse`,
which forwards TCP only. TURN is WebRTC's standard fallback: the phone opens
a TCP connection to this server (like it already does for the web page) and
asks for a "relay" UDP port on the Mac. That port appears as one more ICE
candidate; aiortc on the same Mac talks to it over UDP, and we shuttle the
packets through the phone's TCP connection. When direct UDP works (normal
Wi-Fi), ICE prefers it and this relay just sits idle.

Implements the subset of RFC 8656 that browsers use: Allocate (long-term
credentials), Refresh, CreatePermission, ChannelBind, Send/Data indications
and ChannelData. Simplifications that are fine for a local, single-user relay:
one fixed nonce, and allocations/permissions live as long as the TCP
connection (TURN-over-TCP deletes the allocation when the connection closes).
The relay only forwards to this Mac's own addresses, so it can't be abused as
an open relay into the LAN or the internet.
"""

import asyncio
import hashlib
import logging
import secrets
import struct
from collections.abc import Callable

from aioice import stun

log = logging.getLogger(__name__)

REALM = "phonecam"
LIFETIME = 600  # seconds, as advertised; the TCP connection is what really bounds it
UDP_TRANSPORT = 0x11000000  # REQUESTED-TRANSPORT value for UDP (protocol 17)

# aioice's STUN table lacks DATA (0x0013), used by Send/Data indications.
if "DATA" not in stun.ATTRIBUTES_BY_NAME:
    _data_attr = (0x0013, "DATA", stun.pack_bytes, stun.unpack_bytes)
    stun.ATTRIBUTES_BY_TYPE[0x0013] = _data_attr
    stun.ATTRIBUTES_BY_NAME["DATA"] = _data_attr


def _is_channel_data(data: bytes) -> bool:
    # STUN messages start with bits 00, ChannelData with 01 (channels 0x4000-0x7FFF).
    return (data[0] & 0xC0) == 0x40


def _padded(data: bytes) -> bytes:
    # Over TCP, ChannelData must be padded to a multiple of 4 bytes.
    return data + bytes(stun.padding_length(len(data)))


class TurnServer:
    def __init__(self, port: int, allowed_peer: Callable[[str], bool]) -> None:
        self.port = port
        self.allowed_peer = allowed_peer  # is this IP one of the Mac's own addresses?
        # Fresh random credentials per run; the phone gets them from GET /config over HTTPS.
        self.username = secrets.token_hex(8)
        self.password = secrets.token_hex(16)
        # Long-term credential key (RFC 8489 section 9.2.2).
        self.key = hashlib.md5(f"{self.username}:{REALM}:{self.password}".encode()).digest()
        self.nonce = secrets.token_hex(16).encode()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = await loop.create_server(lambda: _TurnConnection(self), "0.0.0.0", self.port)
        log.info("TURN relay (TCP) listening on port %d", self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def ice_server(self, host: str) -> dict:
        """The RTCIceServer entry the phone page should use to reach us at `host`."""
        return {"urls": [f"turn:{host}:{self.port}?transport=tcp"], "username": self.username, "credential": self.password}


class _RelayProtocol(asyncio.DatagramProtocol):
    """The allocated UDP port on the Mac: packets from aiortc arrive here."""

    def __init__(self, conn: "_TurnConnection") -> None:
        self.conn = conn

    def datagram_received(self, data: bytes, addr) -> None:
        self.conn.relay_received(data, addr[:2])


class _TurnConnection(asyncio.Protocol):
    """One phone's TCP connection, holding at most one allocation."""

    def __init__(self, server: TurnServer) -> None:
        self.server = server
        self.buffer = b""
        self.transport: asyncio.Transport | None = None
        self.peer: tuple[str, int] = ("", 0)
        self.relay: asyncio.DatagramTransport | None = None
        self.permissions: set[str] = set()
        self.channel_to_peer: dict[int, tuple[str, int]] = {}
        self.peer_to_channel: dict[tuple[str, int], int] = {}

    # ----- TCP side (phone) -----

    def connection_made(self, transport) -> None:
        self.transport = transport
        self.peer = transport.get_extra_info("peername")[:2]
        log.debug("TURN connection from %s", self.peer)

    def connection_lost(self, exc) -> None:
        if self.relay:
            self.relay.close()
            log.info("TURN relay for %s closed", self.peer[0])
        self.relay = None

    def data_received(self, data: bytes) -> None:
        # TCP is a byte stream: split it into STUN messages and ChannelData frames.
        self.buffer += data
        while len(self.buffer) >= 4:
            first, length = struct.unpack("!HH", self.buffer[:4])
            if _is_channel_data(self.buffer):
                total = 4 + length + stun.padding_length(length)
                if len(self.buffer) < total:
                    return
                frame, self.buffer = self.buffer[:total], self.buffer[total:]
                self._channel_data(first, frame[4 : 4 + length])
            else:
                total = stun.HEADER_LENGTH + length
                if len(self.buffer) < total:
                    return
                raw, self.buffer = self.buffer[:total], self.buffer[total:]
                self._stun(raw)

    def _channel_data(self, channel: int, payload: bytes) -> None:
        addr = self.channel_to_peer.get(channel)
        if addr and self.relay:
            self.relay.sendto(payload, addr)

    def _stun(self, raw: bytes) -> None:
        try:
            msg = stun.parse_message(raw)
        except ValueError as exc:
            log.debug("TURN: dropping malformed message from %s: %s", self.peer, exc)
            return

        if msg.message_class == stun.Class.INDICATION:
            if msg.message_method == stun.Method.SEND:
                addr = msg.attributes.get("XOR-PEER-ADDRESS")
                data = msg.attributes.get("DATA")
                if addr and data is not None and self.relay and addr[0] in self.permissions:
                    self.relay.sendto(data, addr)
            return
        if msg.message_class != stun.Class.REQUEST:
            return

        if msg.message_method == stun.Method.BINDING:
            self._reply(msg, {"XOR-MAPPED-ADDRESS": self.peer}, sign=False)
            return

        # Everything else needs long-term credentials. The first Allocate comes
        # without them; the 401 tells the browser our realm and nonce.
        if "MESSAGE-INTEGRITY" not in msg.attributes or msg.attributes.get("USERNAME") != self.server.username:
            self._error(msg, 401, "Unauthorized", sign=False)
            return
        try:
            stun.parse_message(raw, integrity_key=self.server.key)
        except ValueError:
            self._error(msg, 401, "Unauthorized", sign=False)
            return

        handler = {
            stun.Method.ALLOCATE: self._allocate,
            stun.Method.REFRESH: self._refresh,
            stun.Method.CREATE_PERMISSION: self._create_permission,
            stun.Method.CHANNEL_BIND: self._channel_bind,
        }.get(msg.message_method)
        if handler is None:
            self._error(msg, 400, "Bad Request")
        else:
            asyncio.ensure_future(handler(msg))

    async def _allocate(self, msg: stun.Message) -> None:
        if self.relay:
            self._error(msg, 437, "Allocation Mismatch")
            return
        if msg.attributes.get("REQUESTED-TRANSPORT") != UDP_TRANSPORT:
            self._error(msg, 442, "Unsupported Transport Protocol")
            return
        # Put the relay on the Mac address the phone reached us at (aiortc runs
        # on this same Mac, so it can always send there). Binding to exactly
        # that address keeps the source of relayed packets equal to the
        # advertised relay address, which ICE checks.
        local_ip = self.transport.get_extra_info("sockname")[0]
        loop = asyncio.get_running_loop()
        self.relay, _ = await loop.create_datagram_endpoint(lambda: _RelayProtocol(self), local_addr=(local_ip, 0))
        relay_addr = self.relay.get_extra_info("sockname")[:2]
        log.info("TURN relay for %s at %s:%d", self.peer[0], *relay_addr)
        self._reply(msg, {
            "XOR-RELAYED-ADDRESS": relay_addr,
            "XOR-MAPPED-ADDRESS": self.peer,
            "LIFETIME": LIFETIME,
        })

    async def _refresh(self, msg: stun.Message) -> None:
        lifetime = msg.attributes.get("LIFETIME", LIFETIME)
        if lifetime == 0 and self.relay:
            self.relay.close()
            self.relay = None
        self._reply(msg, {"LIFETIME": min(lifetime, LIFETIME)})

    def _permit(self, msg: stun.Message) -> tuple[str, int] | None:
        addr = msg.attributes.get("XOR-PEER-ADDRESS")
        if not self.relay:
            self._error(msg, 437, "Allocation Mismatch")
            return None
        if not addr or not self.server.allowed_peer(addr[0]):
            self._error(msg, 403, "Forbidden")  # only this Mac's own addresses
            return None
        self.permissions.add(addr[0])
        return addr

    async def _create_permission(self, msg: stun.Message) -> None:
        if self._permit(msg):
            self._reply(msg, {})

    async def _channel_bind(self, msg: stun.Message) -> None:
        channel = msg.attributes.get("CHANNEL-NUMBER", 0)
        if not 0x4000 <= channel <= 0x7FFF:
            self._error(msg, 400, "Bad Request")
            return
        addr = self._permit(msg)
        if addr:
            self.channel_to_peer[channel] = addr
            self.peer_to_channel[addr] = channel
            self._reply(msg, {})

    # ----- UDP side (aiortc on this Mac) -----

    def relay_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] not in self.permissions or not self.transport or self.transport.is_closing():
            return
        channel = self.peer_to_channel.get(addr)
        if channel is not None:
            self.transport.write(_padded(struct.pack("!HH", channel, len(data)) + data))
        else:
            ind = stun.Message(stun.Method.DATA, stun.Class.INDICATION, attributes={"XOR-PEER-ADDRESS": addr, "DATA": data})
            self.transport.write(bytes(ind))

    # ----- responses -----

    def _reply(self, msg: stun.Message, attributes: dict, sign: bool = True) -> None:
        self._send(stun.Message(msg.message_method, stun.Class.RESPONSE, msg.transaction_id, attributes), sign)

    def _error(self, msg: stun.Message, code: int, reason: str, sign: bool = True) -> None:
        attributes = {"ERROR-CODE": (code, reason)}
        if code == 401:
            attributes.update({"REALM": REALM, "NONCE": self.server.nonce})
        self._send(stun.Message(msg.message_method, stun.Class.ERROR, msg.transaction_id, attributes), sign)

    def _send(self, response: stun.Message, sign: bool) -> None:
        if sign:
            response.add_message_integrity(self.server.key)
        if self.transport and not self.transport.is_closing():
            self.transport.write(bytes(response))
