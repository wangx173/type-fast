# Development

- [Requirements](#requirements)
- [Run from source](#run-from-source)
- [Run tests](#run-tests)
- [Build the macOS app](#build-the-macos-app)
- [Update the app icon](#update-the-app-icon)

## Requirements

- macOS
- Python 3.10 or newer
- An OpenAI API key, or an Azure AI Foundry endpoint and API key (see
  [Configuration](configuration.md))

## Run from source

```sh
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the app and its dependencies
pip install -e .

# Provide your API key (or use a key file; see Configuration)
export OPENAI_API_KEY='sk-...'

# Start the app
type-fast            # or: python -m type_fast.app
```

## Run tests

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

## Build the macOS app

Package Type Fast as a standalone `.app` bundle, with no Python or terminal
needed to run it, using PyInstaller:

```sh
pip install pyinstaller
pyinstaller --noconfirm "Type Fast.spec"

# Optional: ad-hoc sign so it launches with less Gatekeeper friction
codesign --force --deep --sign - "dist/Type Fast.app"
```

The bundle is created at `dist/Type Fast.app`; drag it into `/Applications`.
Put your key in `~/.type-fast/api_key` so the app can reach the API when
launched from Finder.

Pushing a version tag (for example `v0.4.0`) runs the
[release workflow](../.github/workflows/release.yml), which builds the app and
attaches `Type-Fast-macos-arm64.zip` to a GitHub Release.

## Update the app icon

The icon's master file is [`assets/icon/type-fast.svg`](../assets/icon/type-fast.svg):
a keyboard key labeled "A" and "文" with speed lines, on a macOS-style rounded
square. After you edit it, regenerate the derived files (macOS only, because it
uses `iconutil`):

```sh
python scripts/build_icon.py
```

This writes `assets/icon/TypeFast.icns`, which the `.app` bundle uses, and
`type_fast/resources/icon.png`, which the app shows in the Dock and window when
run from source. Commit all three files. Check the result at small sizes
(16 and 32 px), where only the white key on the indigo background stays
readable.

The icon is original artwork drawn with plain SVG shapes, without fonts or
third-party images, and is covered by the project's [MIT license](../LICENSE).
