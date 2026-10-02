# Development

- [Requirements](#requirements)
- [Run from source](#run-from-source)
- [Run tests](#run-tests)
- [Build the macOS app](#build-the-macos-app)

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
