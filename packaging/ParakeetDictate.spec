# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Spec für die Menüleisten-App "Parakeet Dictate".
# Build (aus der Repo-Wurzel):
#     .venv/bin/pyinstaller --noconfirm packaging/ParakeetDictate.spec
# Ergebnis: dist/Parakeet Dictate.app  (unsigniert; Signierung via sign_notarize_dmg.sh)

import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging  ->  Repo-Wurzel

# Native/„schwierige" Pakete vollständig einsammeln (Binaries, Daten, Submodule).
# Bewiesen nötig zur Laufzeit: mlx (Metal), parakeet_mlx, numba, llvmlite,
# librosa, scipy, soundfile. Rest zur Sicherheit.
datas, binaries, hiddenimports = [], [], []
for pkg in [
    "mlx", "parakeet_mlx", "numba", "llvmlite", "librosa", "scipy",
    "soundfile", "soxr", "huggingface_hub", "pynput", "rumps", "pyperclip",
]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# pyobjc-Frameworks für die nativen Berechtigungs-Abfragen im Onboarding
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
    console=False,                 # Menüleisten-App, kein Terminalfenster
    target_arch="arm64",           # nur Apple Silicon
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
    _ICON = None  # ohne Icon bauen, falls noch keins erzeugt wurde (make_icon.py)

app = BUNDLE(
    coll,
    name="Parakeet Dictate.app",
    icon=_ICON,
    bundle_identifier="digital.zelger.parakeetdictate",
    version="1.0.0",
    info_plist={
        "LSUIElement": True,       # nur Menüleiste, kein Dock-Icon
        "NSMicrophoneUsageDescription":
            "Parakeet Dictate nimmt dein Mikrofon auf, um Sprache lokal zu Text zu transkribieren.",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
    },
)
