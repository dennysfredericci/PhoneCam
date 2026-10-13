"""The TURN-over-TCP relay, driven by aioice's own TURN client."""

import asyncio

import pytest
from aioice import stun
from aioice import turn as aioice_turn

from helpers import free_port
from phonecam.turn import TurnServer


class _Echo(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        self.transport.sendto(b"echo:" + data, addr)


class _Inbox(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue = asyncio.Queue()

    def datagram_received(self, data, addr):
        self.queue.put_nowait(data)


def test_relay_forwards_both_ways_and_only_to_allowed_peers():
    async def scenario():
        loop = asyncio.get_running_loop()
        server = TurnServer(free_port(), allowed_peer=lambda ip: ip == "127.0.0.1")
        await server.start()
        echo, _ = await loop.create_datagram_endpoint(_Echo, local_addr=("127.0.0.1", 0))
        relay, inbox = await aioice_turn.create_turn_endpoint(
            _Inbox, server_addr=("127.0.0.1", server.port),
            username=server.username, password=server.password, transport="tcp",
        )
        try:
            # client -> TCP -> relay -> UDP echo -> relay -> TCP -> client
            for i in range(3):
                relay.sendto(b"ping%d" % i, echo.get_extra_info("sockname"))
                assert await asyncio.wait_for(inbox.queue.get(), 5) == b"echo:ping%d" % i

            # The relay must refuse to reach anything but the Mac itself. aioice
            # (pinned) keeps its TURN client private, hence the mangled name.
            client = relay._TurnTransport__inner_protocol
            with pytest.raises(stun.TransactionFailed, match="403"):
                await client.channel_bind(0x4FFF, ("8.8.8.8", 53))
        finally:
            relay.close()
            echo.close()
            await server.stop()

    asyncio.run(scenario())


def test_relay_rejects_wrong_password():
    async def scenario():
        server = TurnServer(free_port(), allowed_peer=lambda ip: True)
        await server.start()
        try:
            with pytest.raises(Exception, match="401"):
                await aioice_turn.create_turn_endpoint(
                    _Inbox, server_addr=("127.0.0.1", server.port),
                    username=server.username, password="wrong", transport="tcp",
                )
        finally:
            await server.stop()

    asyncio.run(scenario())
