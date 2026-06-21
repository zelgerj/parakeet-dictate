# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the menu-bar app "Parakeet Dictate".
# Build (from the repo root):
#     .venv/bin/pyinstaller --noconfirm packaging/ParakeetDictate.spec
# Result: dist/Parakeet Dictate.app  (unsigned; sign it via sign_notarize_dmg.sh)

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging  ->  repo root

# Fully collect the native/"tricky" packages (binaries, data, submodules).
# Proven to be needed at runtime: mlx (Metal), parakeet_mlx, numba, llvmlite,
# librosa, scipy, soundfile. The rest are included to be safe.
datas, binaries, hiddenimports = [], [], []
for pkg in [
    "mlx", "parakeet_mlx", "numba", "llvmlite", "librosa", "scipy",
    "soundfile", "soxr", "huggingface_hub", "pynput", "rumps", "pyperclip",
]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# pyobjc frameworks for the native permission requests in the onboarding flow
hiddenimports += ["ApplicationServices", "Quartz", "AVFoundation"]

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ParakeetDictate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # menu-bar app, no terminal window
    target_arch="arm64",           # Apple Silicon only
    entitlements_file=os.path.join(SPECPATH, "entitlements.plist"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ParakeetDictate",
)

_ICON = os.path.join(SPECPATH, "icon.icns")
if not os.path.exists(_ICON):
    _ICON = None  # build without an icon if none was generated yet (make_icon.py)

app = BUNDLE(
    coll,
    name="Parakeet Dictate.app",
    icon=_ICON,
    bundle_identifier="digital.zelger.parakeetdictate",
    version="1.0.0",
    info_plist={
        "LSUIElement": True,       # menu bar only, no Dock icon
        "NSMicrophoneUsageDescription":
            "Parakeet Dictate records your microphone to transcribe speech to text locally.",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
    },
)
