"""Draw PhoneCam's app icon and pack it as assets/PhoneCam.icns.

    .venv/bin/python assets/make_icon.py

The icon is plain vector drawing with AppKit (no SF Symbols: Apple's licence
doesn't allow them in app icons), so it's rendered sharp at every size.
Only needed when the design changes; the .icns is committed.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSDeviceRGBColorSpace,
    NSColor,
    NSGradient,
    NSGraphicsContext,
    NSPNGFileType,
)

HERE = Path(__file__).resolve().parent


def rgb(hex_color: str) -> NSColor:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)


def oval(cx: float, cy: float, radius: float) -> NSBezierPath:
    return NSBezierPath.bezierPathWithOvalInRect_(((cx - radius, cy - radius), (2 * radius, 2 * radius)))


def draw(size: int) -> bytes:
    """Render the 1024-unit design at `size` pixels and return PNG bytes."""
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    s = size / 1024  # design units -> pixels

    # Background tile: Apple's icon grid puts the 824-unit shape in a 1024 canvas.
    tile = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((100 * s, 100 * s), (824 * s, 824 * s)), 185 * s, 185 * s)
    NSGradient.alloc().initWithStartingColor_endingColor_(rgb("#1B3F9E"), rgb("#3B8BFF")).drawInBezierPath_angle_(tile, 90)

    # Phone body.
    rgb("#FFFFFF").setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((347 * s, 232 * s), (330 * s, 560 * s)), 62 * s, 62 * s).fill()

    # Camera lens: dark ring, blue glass, small highlight.
    cx, cy = 512 * s, 540 * s
    rgb("#10224F").setFill()
    oval(cx, cy, 108 * s).fill()
    NSGradient.alloc().initWithStartingColor_endingColor_(rgb("#2A5BC9"), rgb("#6FB1FF")).drawInBezierPath_angle_(oval(cx, cy, 70 * s), 90)
    rgb("#FFFFFF").setFill()
    oval(cx + 26 * s, cy + 28 * s, 16 * s).fill()

    # Red "live" dot.
    rgb("#FF3B30").setFill()
    oval(512 * s, 330 * s, 28 * s).fill()

    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, {}))


def main() -> None:
    work = Path(tempfile.mkdtemp())
    iconset = work / "PhoneCam.iconset"
    iconset.mkdir()
    for points in (16, 32, 128, 256, 512):
        (iconset / f"icon_{points}x{points}.png").write_bytes(draw(points))
        (iconset / f"icon_{points}x{points}@2x.png").write_bytes(draw(points * 2))
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "PhoneCam.icns")], check=True)
    (HERE / "PhoneCam-1024.png").write_bytes(draw(1024))  # preview, for the README/releases
    shutil.rmtree(work)
    print("Wrote", HERE / "PhoneCam.icns")


if __name__ == "__main__":
    main()
