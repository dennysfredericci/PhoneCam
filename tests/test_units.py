"""Small, fast tests of individual functions."""

import asyncio
import json
import logging

import av
import numpy as np
from cryptography import x509

from phonecam import certs, paths
from phonecam.server import _candidates, _ignore_stale_stun_retries, _tune_answer_sdp
from phonecam.vcam import HEIGHT, WIDTH, _draw

ANSWER = (
    "v=0\r\n"
    "a=candidate:1 1 udp 2130706431 192.168.1.5 50000 typ host\r\n"
    "a=candidate:2 1 udp 16777215 192.168.1.5 50001 typ relay raddr 0.0.0.0 rport 0\r\n"
    "a=rtpmap:102 H264/90000\r\n"
    "a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\n"
    "a=fmtp:103 apt=102\r\n"
)


def test_answer_allows_1080p_and_fast_start():
    sdp = _tune_answer_sdp(ANSWER)
    assert "profile-level-id=42e033;x-google-start-bitrate=4000\r\n" in sdp  # level 5.1, CRLF kept
    assert "a=fmtp:103 apt=102\r\n" in sdp  # RTX line untouched


def test_candidates_summary():
    assert _candidates(ANSWER) == "udp 192.168.1.5:50000 host, udp 192.168.1.5:50001 relay"
    assert _candidates("v=0\r\n") == "none"


def _solid_frame(width, height):
    return av.VideoFrame.from_ndarray(np.full((height, width, 3), 255, np.uint8), format="rgb24")


def test_portrait_gets_black_bars_not_stretched():
    canvas = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    _draw(canvas, _solid_frame(1080, 1920))
    assert canvas[:, WIDTH // 2].min() > 200  # centre column is picture
    assert canvas[:, :100].max() == 0 and canvas[:, -100:].max() == 0  # side bars are black
    content_width = (canvas[HEIGHT // 2, :, 0] > 0).sum()
    assert abs(content_width - 608) <= 2  # 1080 * 1080/1920, aspect ratio kept


def test_landscape_fills_frame_and_none_is_black():
    canvas = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    _draw(canvas, _solid_frame(1280, 720))
    assert canvas.min() > 200
    _draw(canvas, None)
    assert canvas.max() == 0


def test_settings_create_pin_once_and_keep_it(isolated_home):
    first = paths.load_settings()
    assert first["port"] == 8443 and first["turn_port"] == 3478
    assert len(first["pin"]) == 6 and first["pin"].isdigit()
    assert paths.load_settings()["pin"] == first["pin"]  # persisted, not regenerated

    settings_file = paths.support_dir() / "settings.json"
    settings_file.write_text(json.dumps({"port": 9000, "pin": ""}))
    loaded = paths.load_settings()
    assert loaded["pin"] == "" and loaded["port"] == 9000  # "" = protection off, respected
    assert loaded["turn_port"] == 3478  # missing keys filled in


def _cert_ips(path):
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}


def test_certificate_regenerated_only_when_ip_changes():
    cert, _ = certs.ensure_certificate(["10.0.0.5"])
    assert {"10.0.0.5", "127.0.0.1"} <= _cert_ips(cert)
    before = cert.read_bytes()
    certs.ensure_certificate(["10.0.0.5"])
    assert cert.read_bytes() == before  # same IP: reused (the phone doesn't re-accept it)
    certs.ensure_certificate(["10.0.0.9"])
    assert "10.0.0.9" in _cert_ips(cert)


def test_stale_stun_retry_error_is_hidden_but_others_are_not(caplog):
    class Transaction:  # same qualified name as aioice.stun.Transaction
        def __retry(self):
            self.protocol.send_stun()  # protocol is None: like a closed socket

        def schedule(self, loop):
            return loop.call_soon(self.__retry)

    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_ignore_stale_stun_retries)
    with caplog.at_level(logging.DEBUG):
        Transaction().schedule(loop)
        loop.call_soon(lambda: 1 / 0)
        loop.call_soon(loop.stop)
        loop.run_forever()
    loop.close()
    assert "Ignored a STUN retry" in caplog.text
    assert "Exception in callback Transaction" not in caplog.text
    assert "ZeroDivisionError" in caplog.text
