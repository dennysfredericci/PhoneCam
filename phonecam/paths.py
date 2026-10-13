"""Locations of bundled resources and writable files.

Two rules that keep the app packageable:
  * Read-only resources (the phone web page) are looked up relative to the
    code. Inside a PyInstaller bundle the code lives in a temporary/frozen
    location exposed as ``sys._MEIPASS``; from source it's this package dir.
  * Anything we write (certificate, settings, logs) goes to
    ~/Library/Application Support/PhoneCam. The .app bundle must stay
    read-only, otherwise macOS code-signature checks and updates break.
"""

import json
import logging
import logging.handlers
import secrets
import sys
from pathlib import Path

APP_NAME = "PhoneCam"
DEFAULT_SETTINGS = {"port": 8443, "turn_port": 3478}


def resource_path(*parts: str) -> Path:
    # PyInstaller's spec copies phonecam/web to "web" at the bundle root,
    # mirroring the layout relative to this file when running from source.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def support_dir() -> Path:
    path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def random_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def is_valid_pin(pin: str) -> bool:
    """4 to 12 digits: the phone page shows a numeric keypad for it."""
    return pin.isdigit() and 4 <= len(pin) <= 12


def load_settings() -> dict:
    """Read settings.json, filling in (and saving) defaults for missing keys.

    "pin" protects streaming: a random 6-digit PIN is generated the first time.
    Set it to "" in the file to turn protection off.
    """
    path = support_dir() / "settings.json"
    stored = {}
    if path.exists():
        try:
            stored = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning("Ignoring invalid %s: %s", path, exc)
            return {**DEFAULT_SETTINGS, "pin": random_pin()}  # don't overwrite the user's file
    settings = {**DEFAULT_SETTINGS, **stored}
    settings.setdefault("pin", random_pin())
    settings["pin"] = str(settings["pin"])
    if settings != stored:
        path.write_text(json.dumps(settings, indent=2) + "\n")
    return settings


def save_setting(key: str, value) -> None:
    """Change one value in settings.json, keeping everything else in the file."""
    path = support_dir() / "settings.json"
    settings = load_settings()
    settings[key] = value
    path.write_text(json.dumps(settings, indent=2) + "\n")


def setup_logging(debug: bool = False) -> Path:
    log_file = support_dir() / "phonecam.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2)
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console)
    # aiortc/aioice are very chatty; --debug shows every ICE connectivity check.
    for noisy in ("aioice", "aiortc"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if debug else logging.WARNING)
    return log_file
