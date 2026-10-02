# Type Fast

A simple macOS input tool that translates what you type between many languages
(English, Japanese, Chinese, Korean, Spanish, French, German, and more) using
the OpenAI API. Type in one box and the translation
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

- source and target language pickers with a ⇄ swap button (see
  [Languages](#languages)),
- a tone selector for the translation (see [Tone](#tone)),
- an input box,
- an output box that streams the translation, and
- the active model, shown at the bottom left.

Translation fires shortly after you stop typing, or immediately when your text
ends in sentence-ending punctuation (`.`, `!`, `?`, `。`, `！`, `？`, `؟`, `।`).

### Languages

Choose the language you type in on the left and the language to translate into
on the right. Supported languages: English, Japanese, Chinese (Simplified),
Chinese (Traditional), Korean, Spanish, French, German, Italian, Portuguese,
Russian, Vietnamese, Thai, Indonesian, Hindi, and Arabic.

- **Auto-detect** as the source lets the model work out the input language.
- **⇄** swaps the source and target. It is disabled while the source is
  Auto-detect.
- Picking the same language on both sides swaps the pair instead.
- Changing either language re-translates the current text.

The pair is saved to `~/.type-fast/settings.json` (with the tone) and restored
on launch. To add a language, add an entry to `LANGUAGES` in
[`type_fast/config.py`](type_fast/config.py).

### Tone

Pick the tone of the translated text from the selector next to the language
pickers: **Polite** (default), **Casual**, **Formal**, **Business**,
**Friendly**, or **Neutral** (mirror the original). Choose **Custom…** — or
**Settings → Set Custom Tone…** — to write your own instruction, such as
"Humble keigo (謙譲語) for a client" or "Playful, with a light touch of humor".
The instruction is added to the translation prompt.

Changing the tone re-translates the current text. Your choice (and custom
instruction) is saved to `~/.type-fast/settings.json` and restored on launch.

## Configuration

Defaults live in [`type_fast/config.py`](type_fast/config.py): the default
model, the models suggested in the model picker, temperature, supported
languages and the default language pair, tone presets, and the debounce
interval. Provider selection (OpenAI vs.
Azure AI Foundry) is driven by the environment variables described under
[Setup](#setup).

### Switch the model

Choose **Settings → Set Model…** to pick a model from the list or type any
model/deployment name. Leave it blank to go back to the default
(`gpt-4.1-mini`). The choice applies to the active provider and is saved to a
file under `~/.type-fast/`. You can also set it by hand or with an environment
variable, which takes precedence over the file:

| Provider         | Environment variable | Fallback file                   |
|------------------|----------------------|---------------------------------|
| OpenAI           | `OPENAI_MODEL`       | `~/.type-fast/openai_model`     |
| Azure AI Foundry | `AZURE_AI_MODEL`     | `~/.type-fast/azure_ai_model`   |

Reasoning models (`gpt-5*`, `o1`, `o3`, `o4` families) do not accept a
`temperature` setting, so it is omitted for them automatically. If a
custom-named deployment rejects `temperature`, the request is retried without
it and that deployment is remembered for the rest of the session.

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
- A menu-bar wrapper.
