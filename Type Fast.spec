# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Type Fast — builds a macOS bundle or Windows folder.

Build:
    pip install pyinstaller
    pyinstaller --noconfirm "Type Fast.spec"

Result: dist/Type Fast.app on macOS; dist/Type Fast/Type Fast.exe on Windows.

Type Fast reads your OpenAI API key from the OPENAI_API_KEY environment
variable or, since a Finder-launched app does not inherit your shell
environment, from ~/.type-fast/api_key:
    mkdir -p ~/.type-fast && echo 'sk-...' > ~/.type-fast/api_key
"""

import sys

if sys.platform not in ("darwin", "win32"):
    raise RuntimeError("Type Fast packaging supports macOS and Windows only")

block_cipher = None

a = Analysis(
    ["launch.py"],
    pathex=[],
    binaries=[],
    # Window/Dock icon set at runtime (see type_fast.app.app_icon).
    datas=[("type_fast/resources/icon.png", "type_fast/resources")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == "darwin":
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
else:
    from importlib.metadata import version

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    product_version = version("type-fast")
    version_parts = tuple(int(part) for part in product_version.split("."))
    if not 1 <= len(version_parts) <= 4 or any(
        not 0 <= part <= 65535 for part in version_parts
    ):
        raise ValueError("Windows packaging requires a numeric version with 1-4 components")
    file_version = version_parts + (0,) * (4 - len(version_parts))
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=file_version, prodvers=file_version, fileType=0x1,
        ),
        kids=[
            StringFileInfo([
                StringTable("040904B0", [
                    StringStruct("FileDescription", "Type Fast"),
                    StringStruct("FileVersion", product_version),
                    StringStruct("InternalName", "Type Fast"),
                    StringStruct("OriginalFilename", "Type Fast.exe"),
                    StringStruct("ProductName", "Type Fast"),
                    StringStruct("ProductVersion", product_version),
                ]),
            ]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )
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
        argv_emulation=False,
        icon="assets/icon/TypeFast.ico",
        version=version_info,
    )

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Type Fast",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Type Fast.app",
        # Exported from assets/icon/type-fast.svg.
        icon="assets/icon/TypeFast.icns",
        bundle_identifier="com.typefast.app",
        info_plist={
            "CFBundleName": "Type Fast",
            "CFBundleDisplayName": "Type Fast",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "LSMinimumSystemVersion": "12.0",
            "LSApplicationCategoryType": "public.app-category.productivity",
            "NSHighResolutionCapable": True,
            # Shown when macOS asks for microphone access for voice input.
            "NSMicrophoneUsageDescription": (
                "Type Fast records your voice when you start voice input, to "
                "transcribe it for translation."
            ),
        },
    )
