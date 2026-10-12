"""Command-line entry point.

    python -m phonecam                 # serve the phone page, feed the virtual camera
    python -m phonecam --port 9443     # different port (default from settings.json)
    python -m phonecam --test-pattern  # no phone: send a test pattern to the camera
"""

import argparse
import asyncio
import logging
import sys
import threading

from .paths import load_settings, setup_logging, support_dir
from .server import PhoneCamServer
from .vcam import VirtualCamera, VirtualCameraError, run_test_pattern

log = logging.getLogger("phonecam")


async def _serve(vcam: VirtualCamera, port: int, turn_port: int, pin: str) -> None:
    server = PhoneCamServer(vcam, port, turn_port, pin)
    try:
        await server.start()
    except OSError as exc:
        sys.exit(f"Cannot listen on port {port} ({exc.strerror}). Is PhoneCam already running? Try --port.")
    print("\nOpen this URL on your phone (same Wi-Fi):")
    for url in server.urls or ["(no network found - connect to Wi-Fi)"]:
        print(f"    {url}")
    print(f"PIN: {pin}" if pin else "No PIN (anyone on the network can connect; set \"pin\" in settings.json).")
    print("Press Ctrl+C to quit.\n")
    try:
        await asyncio.Event().wait()  # run until Ctrl+C
    finally:
        await server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(prog="phonecam", description="Use your phone as a webcam via the OBS Virtual Camera.")
    parser.add_argument("--port", type=int, help="HTTPS port (default: settings.json, 8443)")
    parser.add_argument("--debug", action="store_true", help="log WebRTC/ICE details (connection troubleshooting)")
    parser.add_argument("--test-pattern", action="store_true", help="send a test pattern instead of serving the phone page")
    args = parser.parse_args()

    log_file = setup_logging(args.debug)
    settings = load_settings()
    port = args.port or int(settings["port"])
    log.info("Data folder: %s (log: %s)", support_dir(), log_file.name)

    vcam = VirtualCamera()
    try:
        vcam.start()
    except VirtualCameraError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 1

    try:
        if args.test_pattern:
            print("Sending a test pattern to 'OBS Virtual Camera' (landscape/portrait every 5 s). Ctrl+C to stop.")
            run_test_pattern(vcam, threading.Event())
        else:
            asyncio.run(_serve(vcam, port, int(settings["turn_port"]), settings["pin"]))
    except KeyboardInterrupt:
        pass
    finally:
        vcam.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
