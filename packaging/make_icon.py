#!/usr/bin/env python3
"""Erzeugt packaging/icon.icns — schlichtes Mikrofon-Icon auf Farbverlauf.

Nutzung:  .venv/bin/python packaging/make_icon.py
Braucht nur pyobjc (ist Dependency) + sips/iconutil (macOS-Bordmittel).
"""
import os
import subprocess
import tempfile

from AppKit import (
    NSImage, NSBitmapImageRep, NSColor, NSBezierPath, NSFont,
    NSAttributedString, NSFontAttributeName, NSGradient,
)

try:
    from AppKit import NSBitmapImageFileTypePNG
except Exception:
    NSBitmapImageFileTypePNG = 4  # Fallback-Konstante für PNG

SIZE = 1024.0
GLYPH = "🎙️"


def _render_master(path):
    img = NSImage.alloc().initWithSize_((SIZE, SIZE))
    img.lockFocus()
    rect = ((0.0, 0.0), (SIZE, SIZE))
    radius = SIZE * 0.22
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius).addClip()
    top = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.37, 0.33, 0.87, 1.0)
    bottom = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.17, 0.15, 0.45, 1.0)
    NSGradient.alloc().initWithStartingColor_endingColor_(top, bottom).drawInRect_angle_(rect, 90.0)
    font = NSFont.systemFontOfSize_(SIZE * 0.52)
    s = NSAttributedString.alloc().initWithString_attributes_(GLYPH, {NSFontAttributeName: font})
    w, h = s.size()
    s.drawAtPoint_(((SIZE - w) / 2.0, (SIZE - h) / 2.0))
    img.unlockFocus()
    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    png.writeToFile_atomically_(path, True)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as tmp:
        master = os.path.join(tmp, "master.png")
        _render_master(master)
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset)
        # (Pixelgröße, Dateiname) gemäß iconutil-Konvention
        for px, name in [
            (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
        ]:
            subprocess.run(
                ["sips", "-z", str(px), str(px), master, "--out", os.path.join(iconset, name)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        out = os.path.join(here, "icon.icns")
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
        print("geschrieben:", out)


if __name__ == "__main__":
    main()
