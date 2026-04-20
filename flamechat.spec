# PyInstaller spec used by all three platforms.
#
# Build with: python -m PyInstaller flamechat.spec --clean --noconfirm
#
# Outputs:
#   macOS   dist/FlameChat.app
#   Windows dist\FlameChat\FlameChat.exe (plus support folder)
#   Linux   dist/FlameChat/FlameChat     (plus support folder)
#
# We intentionally use --onedir, not --onefile. wxPython apps extract too
# much on --onefile and the first-launch delay makes the app feel broken.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)
SRC = ROOT / "src"

block_cipher = None


# Packages that load submodules / native bits dynamically at runtime.
# PyInstaller's static scan misses those, so we pull them in wholesale.
# Symptom of NOT doing this: "Failed to execute script 'flamechat'" the
# moment one of these packages hits its dynamic import path — most
# visibly ``accessible_output2.outputs.auto`` on Windows, which probes
# NVDA/JAWS/SAPI clients by name.
DYNAMIC_PACKAGES = [
    "accessible_output2",  # screen-reader backends + controller DLLs
    "av",                  # PyAV + bundled FFmpeg shared libraries
    "faster_whisper",      # model-loader shims
    "ctranslate2",          # whisper backend, native wheels
    "soundfile",            # libsndfile ships as a dylib / DLL
    "pyloudnorm",
]

collected_datas: list = []
collected_binaries: list = []
collected_hiddenimports: list = []
for pkg in DYNAMIC_PACKAGES:
    try:
        datas, binaries, hiddenimports = collect_all(pkg)
    except Exception:
        # Optional / missing package on a platform → skip, don't hard-fail.
        continue
    collected_datas += datas
    collected_binaries += binaries
    collected_hiddenimports += hiddenimports


a = Analysis(
    [str(SRC / "flamechat" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=collected_binaries,
    datas=[
        # Bundle the plain WAV assets (send + receive). Typing variants live
        # as obfuscated bytes inside ``ui/_typing_*_data.py`` modules and
        # are picked up via normal Python imports; no data file needed.
        (str(SRC / "flamechat" / "assets" / "send.wav"), "flamechat/assets"),
        (str(SRC / "flamechat" / "assets" / "receive.wav"), "flamechat/assets"),
    ] + collected_datas,
    hiddenimports=["wx.adv"] + collected_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim fat: we don't use these wx modules.
        "wx.html2",
        "wx.glcanvas",
        # Science stack we don't actually depend on (we DO use numpy +
        # scipy; leaving those out of excludes so PyInstaller packages
        # them properly).
        "IPython",
        "notebook",
        "matplotlib",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FlameChat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # no terminal window on Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FlameChat",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FlameChat.app",
        icon=None,  # drop an .icns here later if branding becomes a thing
        bundle_identifier="com.flamechat.app",
        info_plist={
            "CFBundleName": "FlameChat",
            "CFBundleDisplayName": "FlameChat",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            # We never access camera/mic/location. Explicitly declare no
            # background usage so macOS does not show ambiguous prompts.
            "LSBackgroundOnly": False,
            "LSApplicationCategoryType": "public.app-category.productivity",
            # Network reachability: outbound only, never listening.
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSAllowsArbitraryLoads": False,
            },
        },
    )
