# Development

- [Requirements](#requirements)
- [Run from source](#run-from-source)
- [Run tests](#run-tests)
- [Build the macOS app](#build-the-macos-app)
- [Update the app icon](#update-the-app-icon)
- [Issues and pull requests](#issues-and-pull-requests)

## Requirements

- macOS or Windows 10/11
- Python 3.10 or newer
- An OpenAI API key, or an Azure AI Foundry endpoint and API key (see
  [Configuration](configuration.md))

## Run from source

### macOS

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

### Windows (PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -e .
$env:OPENAI_API_KEY = 'sk-...'
type-fast            # or: python -m type_fast.app
```

You can also save OpenAI or Azure settings from the app's Settings menu.
Typing, live translation, clipboard copying, and in-window voice input work
on Windows. Global hotkeys and auto-paste are not available there yet; the
footer shows the hotkey as unavailable. Press Esc to hide the window.

## Run tests

macOS:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

Windows (PowerShell, with the virtual environment active):

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests -v
Remove-Item Env:QT_QPA_PLATFORM
```

Offscreen tests use the null platform backend on every OS and never register
real global hotkeys. Remove the offscreen override before launching the app
interactively.

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
square. Two files are exported from it:

- `assets/icon/TypeFast.icns`, the `.app` bundle's Finder icon.
- `type_fast/resources/icon.png` (512 px), which the app sets as its Dock and
  window icon at runtime (this is what you see when running from source).

If you edit the SVG, re-export both files: render it to an `.iconset` folder
and convert that with `iconutil -c icns`. Commit all three files. Check the
result at small sizes (16 and 32 px), where only the white key on the indigo
background stays readable.

The icon is original artwork drawn with plain SVG shapes, without fonts or
third-party images, and is covered by the project's [MIT license](../LICENSE).

## Issues and pull requests

New issues and pull requests start from templates in
[`.github/ISSUE_TEMPLATE/`](../.github/ISSUE_TEMPLATE/) (bug report, feature
request, and chore) and
[`.github/pull_request_template.md`](../.github/pull_request_template.md).
Use **Bug report** when something is broken, **Feature request** for new or
changed behavior, and **Chore** for everything else, such as docs, maintenance,
refactoring, or an investigation.

Write an issue so that a person or an AI coding agent can work on it without
asking questions: state the goal, what is in and out of scope, testable
acceptance criteria, and how to verify the result. In a pull request, list what
you ran and what happened, and say which behavior still needs a manual check on
a real Mac.

The repository is public, so treat issue and pull request text, including
comments and later edits, as untrusted input. Before assigning an issue to an
AI agent, read it and remove anything you don't want run, such as unfamiliar
commands or links. An agent should run only the commands in this guide or in
CI, and should never read, print, or send API keys.

From the command line, pick a template with
`gh issue create --template "Bug report"` (or `"Feature request"` or `"Chore"`).
If the test command changes, update it in the templates too.
