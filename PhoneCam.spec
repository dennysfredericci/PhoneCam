# PyInstaller spec for PhoneCam.app. Build it with ./build.sh, not directly.
#
# The app is built for the CPU of the Python running PyInstaller (arm64 on
# Apple Silicon, x86_64 on Intel). A single "universal" app isn't possible
# because PyAV only publishes separate arm64 and x86_64 packages.

import platform
import re
from pathlib import Path

version = re.search(r'__version__ = "(.+)"', Path("phonecam/__init__.py").read_text()).group(1)
apple_silicon = platform.machine() == "arm64"

a = Analysis(
    ["phonecam/__main__.py"],
    pathex=["."],
    # paths.resource_path("web", ...) finds this under sys._MEIPASS.
    datas=[("phonecam/web", "web")],
    # Imported inside main() only when needed; listed so they're always bundled.
    hiddenimports=["phonecam.menubar", "phonecam.selftest"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PhoneCam",
    console=False,
    argv_emulation=False,
    codesign_identity=None,  # ad-hoc signature: enough to run, but "unidentified developer"
)
coll = COLLECT(exe, a.binaries, a.datas, name="PhoneCam")
app = BUNDLE(
    coll,
    name="PhoneCam.app",
    icon="assets/PhoneCam.icns",  # drawn by assets/make_icon.py
    bundle_identifier="io.github.dennysfredericci.phonecam",
    version=version,
    info_plist={
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSUIElement": True,  # menu-bar only: no Dock icon, no main window
        # PyAV's arm64 libraries need macOS 14; on Intel, the OBS camera extension needs 13.
        "LSMinimumSystemVersion": "14.0" if apple_silicon else "13.0",
        # Shown by macOS 15+ when PhoneCam first talks to the phone on the LAN.
        "NSLocalNetworkUsageDescription": "PhoneCam receives the video from your phone over the local network.",
    },
)
