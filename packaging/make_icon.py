#!/usr/bin/env python3
"""Generate packaging/icon.icns — a clean drawn microphone on an indigo gradient.

Usage:  .venv/bin/python packaging/make_icon.py
Needs only pyobjc (a dependency) + sips/iconutil (macOS built-ins).
A 1024px preview is also written to /tmp/icon_preview.png.
"""
import os
import subprocess
import tempfile

from AppKit import (
    NSImage, NSBitmapImageRep, NSColor, NSBezierPath, NSGradient,
)

try:
    from AppKit import NSBitmapImageFileTypePNG
except Exception:
    NSBitmapImageFileTypePNG = 4
try:
    from AppKit import NSLineCapStyleRound
except Exception:
    NSLineCapStyleRound = 1

S = 1024.0
PREVIEW = "/tmp/icon_preview.png"


def _rounded(x, y, w, h, r):
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x, y), (w, h)), r, r)


def _render_master(path):
    img = NSImage.alloc().initWithSize_((S, S))
    img.lockFocus()

    # Background: rounded square ("squircle"-ish) with a vertical indigo gradient.
    rect = ((0.0, 0.0), (S, S))
    _rounded(0, 0, S, S, 0.225 * S).addClip()
    dark = NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.16, 0.52, 1.0)
    light = NSColor.colorWithSRGBRed_green_blue_alpha_(0.46, 0.39, 0.98, 1.0)
    NSGradient.alloc().initWithStartingColor_endingColor_(dark, light).drawInRect_angle_(rect, 90.0)

    white = NSColor.whiteColor()
    white.setFill()
    white.setStroke()
    cx = S / 2

    # Mic head (vertical capsule)
    cap_w, cap_h = 220.0, 300.0
    _rounded(cx - cap_w / 2, 452.0, cap_w, cap_h, cap_w / 2).fill()

    # Cradle (U-bracket) — stroked bottom arc, a bit wider than the head
    arc = NSBezierPath.bezierPath()
    arc.setLineWidth_(40.0)
    arc.setLineCapStyle_(NSLineCapStyleRound)
    arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
        (cx, 512.0), 196.0, 205.0, 335.0)
    arc.stroke()

    # Stem
    stem = NSBezierPath.bezierPath()
    stem.setLineWidth_(34.0)
    stem.setLineCapStyle_(NSLineCapStyleRound)
    stem.moveToPoint_((cx, 320.0))
    stem.lineToPoint_((cx, 258.0))
    stem.stroke()

    # Base
    _rounded(cx - 115, 236.0, 230.0, 36.0, 18.0).fill()

    img.unlockFocus()
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    png.writeToFile_atomically_(path, True)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    _render_master(PREVIEW)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset)
        # (pixel size, filename) per the iconutil convention
        for px, name in [
            (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
        ]:
            subprocess.run(
                ["sips", "-z", str(px), str(px), PREVIEW, "--out", os.path.join(iconset, name)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        out = os.path.join(here, "icon.icns")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
        print("wrote:", out)
        print("preview:", PREVIEW)


if __name__ == "__main__":
    main()
