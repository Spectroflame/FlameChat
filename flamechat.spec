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

ROOT = Path(SPECPATH)
SRC = ROOT / "src"

block_cipher = None


a = Analysis(
    [str(SRC / "flamechat" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        # Bundle the plain WAV assets (send + receive). Typing variants live
        # as obfuscated bytes inside ``ui/_typing_*_data.py`` modules and
        # are picked up via normal Python imports; no data file needed.
        (str(SRC / "flamechat" / "assets" / "send.wav"), "flamechat/assets"),
        (str(SRC / "flamechat" / "assets" / "receive.wav"), "flamechat/assets"),
    ],
    hiddenimports=["wx.adv"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim fat: we don't use these wx modules.
        "wx.html2",
        "wx.glcanvas",
        # No scientific stack, no notebook — PyInstaller pulls them in
        # for psutil hooks on some systems, but we don't need them.
        "IPython",
        "notebook",
        "matplotlib",
        "numpy",
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
