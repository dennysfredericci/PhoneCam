"""Entry point, for both `python -m phonecam` and the packaged PhoneCam.app.

    python -m phonecam                 # serve the phone page, feed the virtual camera
    python -m phonecam --menubar       # same, as a menu-bar app (what PhoneCam.app runs)
    python -m phonecam --port 9443     # different port (default from settings.json)
    python -m phonecam --test-pattern  # no phone: send a test pattern to the camera
    python -m phonecam --self-test     # check the libraries work (used by build.sh/CI)

Imports are absolute (not `from .x`) because PyInstaller runs this file as a
top-level script inside the app bundle.
"""

import argparse
import asyncio
import logging
import sys
import threading

from phonecam.paths import load_settings, setup_logging, support_dir
from phonecam.server import PhoneCamServer
from phonecam.vcam import VirtualCamera, VirtualCameraError, run_test_pattern

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
    parser.add_argument("--menubar", action="store_true", help="run as a menu-bar app (default inside PhoneCam.app)")
    parser.add_argument("--test-pattern", action="store_true", help="send a test pattern instead of serving the phone page")
    parser.add_argument("--self-test", action="store_true", help="check that all libraries work, then exit")
    # macOS may pass "-psn_..." to apps opened from Finder; ignore unknown args.
    args, _ = parser.parse_known_args()

    if args.self_test:
        from phonecam.selftest import run_self_test

        return run_self_test()

    log_file = setup_logging(args.debug)
    settings = load_settings()
    port = args.port or int(settings["port"])
    log.info("Data folder: %s (log: %s)", support_dir(), log_file.name)

    # Inside the .app there's no terminal, so the menu bar is the default UI.
    if args.menubar or (getattr(sys, "frozen", False) and not args.test_pattern):
        from phonecam.menubar import run_menubar

        return run_menubar(port, int(settings["turn_port"]), settings["pin"])

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
