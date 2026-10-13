"""The server end to end, with aiortc playing the phone (real WebRTC, real H.264)."""

import asyncio

from helpers import http_session, phone_offer, start_server, wait_for


def test_phone_streams_h264_and_stop_shows_black():
    async def scenario():
        server, camera = await start_server()
        try:
            async with http_session() as http:
                async with http.get(f"https://127.0.0.1:{server.port}/") as page:
                    assert page.status == 200 and "PhoneCam" in await page.text()
                pc, status, answer = await phone_offer(http, server, size=(640, 360))
                assert status == 200
                first_codec = next(line for line in answer["sdp"].splitlines() if line.startswith("a=rtpmap"))
                assert "H264" in first_codec
                assert "profile-level-id=42e033" in answer["sdp"]
                await wait_for(lambda: len(camera.frames) >= 30)
                assert camera.frames[-1] == (640, 360)
                await wait_for(lambda: server.connected and "fps" in server.stats)
                assert server.stats.startswith("640×360")
                assert "relay" not in server.stats  # direct path on localhost

                await pc.close()
                await wait_for(lambda: server.pc is None)
                assert camera.blacks > 0 and server.stats == ""
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_second_phone_takes_over_but_cannot_steal_back_automatically():
    async def scenario():
        server, camera = await start_server()
        try:
            async with http_session() as http:
                phone_a, status, _ = await phone_offer(http, server, client_id="A")
                assert status == 200
                await wait_for(lambda: server.connected)

                # An automatic reconnect from another phone must not take over...
                _, status, body = await phone_offer(http, server, client_id="B", reconnect=True)
                assert status == 409, body

                # ...but tapping Start does.
                phone_b, status, _ = await phone_offer(http, server, client_id="B", size=(360, 640))
                assert status == 200
                await wait_for(lambda: camera.frames and camera.frames[-1] == (360, 640))
                assert server.client_id == "B"

                # Now phone A's automatic reconnect is the one refused.
                _, status, _ = await phone_offer(http, server, client_id="A", reconnect=True)
                assert status == 409
                await phone_a.close()
                await phone_b.close()
        finally:
            await server.stop()

    asyncio.run(scenario())


def test_pin_required_and_lockout():
    async def scenario():
        server, _ = await start_server(pin="4321")
        base = f"https://127.0.0.1:{server.port}"
        try:
            async with http_session() as http:

                async def config(pin):
                    async with http.get(f"{base}/config", headers={"X-PhoneCam-PIN": pin}) as r:
                        return r.status, await r.json()

                assert (await config(""))[0] == 401
                status, body = await config("4321")
                assert status == 200 and body["iceServers"][0]["urls"][0].endswith("?transport=tcp")

                _, status, _ = await phone_offer(http, server, pin="")
                assert status == 401  # /offer is protected too

                for _ in range(5):
                    assert (await config("0000"))[0] == 401
                status, body = await config("4321")
                assert status == 429, "even the right PIN is refused during the lockout"
                assert "Try again" in body["error"]
        finally:
            await server.stop()

    asyncio.run(scenario())
