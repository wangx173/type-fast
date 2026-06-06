# type-fast

A simple macOS input tool that translates what you type, bidirectionally between
English and Japanese, using the OpenAI API. Type in one box and the translation
streams into the other.

## Requirements

- macOS
- Python 3.10 or newer
- An OpenAI API key

## Setup

```sh
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install the app and its dependencies
pip install -e .

# 3. Provide your OpenAI API key (environment variable, or a key file — see below)
export OPENAI_API_KEY='sk-...'
```

The key is read from `OPENAI_API_KEY`, or, if that is not set, from
`~/.type-fast/api_key`. The key file is what the packaged app uses, since an app
launched from Finder does not inherit your shell environment:

```sh
mkdir -p ~/.type-fast
echo 'sk-...' > ~/.type-fast/api_key
```

You can also set the key from inside the app: **Settings → Set OpenAI API Key…**
(⌘,). It is saved to `~/.type-fast/api_key` and applied immediately.

## Run

```sh
python -m type_fast.app
# or, via the installed entry point:
type-fast
```

A small always-on-top window opens with:

- a direction toggle (English → Japanese / Japanese → English),
- an input box, and
- an output box that streams the translation.

Translation fires shortly after you stop typing, or immediately when your text
ends in sentence-ending punctuation (`.`, `!`, `?`, `。`, `！`, `？`).

## Configuration

Defaults live in [`type_fast/config.py`](type_fast/config.py): the OpenAI model,
temperature, default language pair, and the debounce interval.

## Build a native macOS app

Package Type Fast as a standalone `.app` bundle (no Python or terminal needed to
run it) with PyInstaller:

```sh
pip install pyinstaller
pyinstaller --noconfirm "Type Fast.spec"

# Optional: ad-hoc sign so it launches without extra Gatekeeper friction
codesign --force --deep --sign - "dist/Type Fast.app"
```

The bundle is created at `dist/Type Fast.app` — drag it into `/Applications`.
Make sure your key is in `~/.type-fast/api_key` (see Setup) so the app can reach
the API when launched from Finder.

## Roadmap (future work)

- Store the API key in the macOS Keychain instead of a key file.
- Sign and notarize the `.app` with a Developer ID for distribution to others.
- A menu-bar wrapper and more language pairs.
