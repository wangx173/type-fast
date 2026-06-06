# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Type Fast — builds a native macOS .app bundle.

Build:
    pip install pyinstaller
    pyinstaller --noconfirm "Type Fast.spec"

Result: dist/Type Fast.app  (drag into /Applications).

Type Fast reads your OpenAI API key from the OPENAI_API_KEY environment
variable or, since a Finder-launched app does not inherit your shell
environment, from ~/.type-fast/api_key:
    mkdir -p ~/.type-fast && echo 'sk-...' > ~/.type-fast/api_key
"""

block_cipher = None

a = Analysis(
    ["launch.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Type Fast",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Type Fast",
)

app = BUNDLE(
    coll,
    name="Type Fast.app",
    icon=None,
    bundle_identifier="com.typefast.app",
    info_plist={
        "CFBundleName": "Type Fast",
        "CFBundleDisplayName": "Type Fast",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "12.0",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
    },
)
