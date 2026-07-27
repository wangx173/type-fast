# Type Fast

A simple macOS input tool that translates what you type, bidirectionally between
English and Japanese, using the OpenAI API. Type in one box and the translation
streams into the other.

## Download

Grab the latest `Type-Fast-macos-arm64.zip` from the
[Releases page](https://github.com/wangx173/type-fast/releases), unzip it, and
drag `Type Fast.app` into `/Applications`.

The app is ad-hoc signed (not notarized), so on first launch macOS will warn it
is from an unidentified developer. To open it the first time: right-click the
app → **Open** → **Open**, or allow it under **System Settings → Privacy &
Security**. After that it launches normally.

Before using it, set your OpenAI API key in the app: **Settings → Set OpenAI API
Key…** (⌘,).

## Requirements

- macOS
- Python 3.10 or newer
- An OpenAI API key, or a Microsoft (Azure AI) Foundry endpoint + API key

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

### Use Microsoft (Azure AI) Foundry instead of OpenAI

To route translations through a Microsoft (Azure AI) Foundry model, set the
Foundry endpoint and API key as environment variables:

```sh
export AZURE_AI_ENDPOINT='https://<resource>.services.ai.azure.com'
export AZURE_AI_API_KEY='<your-foundry-key>'
# Optional: pick a specific model/deployment (defaults to gpt-4.1-mini)
export AZURE_AI_MODEL='gpt-4.1-mini'
```

When both `AZURE_AI_ENDPOINT` and `AZURE_AI_API_KEY` are set, Foundry takes
precedence over OpenAI. The endpoint may be the bare resource URL (shown above)
or already include the `/openai/v1` path — either works, and requests use
Foundry's OpenAI-compatible Responses API.

As with the OpenAI key, each variable has a `~/.type-fast/` fallback file so the
packaged app works when launched from Finder (which does not inherit your shell
environment):

```sh
mkdir -p ~/.type-fast
echo 'https://<resource>.services.ai.azure.com' > ~/.type-fast/azure_ai_endpoint
echo '<your-foundry-key>' > ~/.type-fast/azure_ai_api_key
# Optional model/deployment override:
echo 'gpt-4.1-mini' > ~/.type-fast/azure_ai_model
```

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

## Keyboard-like workflow: global hotkey + auto-paste

Press **⌥⌘Space** (the default; [configurable](#configuration)) from anywhere
on macOS to summon the Type Fast window. When you press the hotkey, Type Fast
remembers whichever app was frontmost; once your translation finishes, it
re-activates that app and simulates **⌘V** so the translated text is pasted
straight into whatever you were typing into, then auto-hides itself — no
manual app-switching or paste required.

This requires granting Type Fast **Accessibility** access (macOS needs this
for any app that monitors global keystrokes or sends synthetic ones):
**Settings → Grant Accessibility Access…**, then enable "Type Fast" (or your
terminal/Python, if running from source) under **System Settings → Privacy &
Security → Accessibility**.

Without Accessibility access, the hotkey and auto-paste are simply inert —
translations still stream normally and are still copied to the clipboard, so
you can fall back to a manual paste.

When the field you were typing into supports it (most native macOS text
fields), Type Fast goes a step further: it anchors its window just below
that field and streams the translation directly into it as you type, so it
reads like an extension of the field itself rather than a separate app —
auto-hiding once the translation finishes. Fields that don't expose a
settable Accessibility value (common in some web/Electron apps) transparently
fall back to the clipboard/auto-paste flow above instead.

## Configuration

Defaults live in [`type_fast/config.py`](type_fast/config.py): the OpenAI model,
the default Foundry model, temperature, default language pair, and the debounce
interval. Provider selection (OpenAI vs. Azure AI Foundry) is driven by the
environment variables described under [Setup](#setup).

### Custom hotkey

The default global hotkey is **⌥⌘Space** (Option+Command+Space). Override it
with the `TYPE_FAST_HOTKEY` environment variable, or — for the packaged
`.app`, which doesn't inherit your shell environment — a `~/.type-fast/hotkey`
file (same fallback pattern as the API key). The value is a `+`-separated
spec of modifiers plus exactly one key, e.g.:

```sh
export TYPE_FAST_HOTKEY="control+shift+t"
# or
echo "control+shift+t" > ~/.type-fast/hotkey
```

Supported modifiers: `cmd`/`command`, `opt`/`option`/`alt`, `ctrl`/`control`,
`shift`. Supported keys: letters, digits, and `space`, `tab`,
`return`/`enter`, `escape`/`esc`, `delete`. An invalid or unparseable spec is
reported on stderr and Type Fast falls back to the default shortcut rather
than failing to start.

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
