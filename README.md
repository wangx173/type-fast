<div align="center">

# Type Fast

**Type in one language. Get it in another — as you type.**

A tiny macOS translator that pops up with a hotkey, streams translations from
OpenAI or Azure AI Foundry, and copies the result for you.

[![CI](https://github.com/wangx173/type-fast/actions/workflows/ci.yml/badge.svg)](https://github.com/wangx173/type-fast/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/wangx173/type-fast)](https://github.com/wangx173/type-fast/releases/latest)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)](#install)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="docs/images/demo.png">
  <img src="docs/images/demo.gif" alt="Demo: in a chat app, pressing ⇧⌘Space pops up Type Fast. Typing &quot;Yes, I will! Are you free for lunch?&quot; streams in a polite Japanese translation, which is copied to the clipboard. Pressing ⇧⌘Space again hides Type Fast, and ⌘V pastes the Japanese reply into the chat." width="720">
</picture>

<sub>Press <b>⇧⌘Space</b> in any app, type, and paste the translation with <b>⌘V</b>.</sub>

</div>

## Features

- ⚡ **Live translation** — the translation streams in as you type; as you keep
  typing, finished lines aren't re-translated.
- ⌨️ **Spotlight-style hotkey** — press **⇧⌘Space** in any app to pop up a
  minimal window; press it again or **Esc** to go back.
- 🪟 **Stays out of your way** — the window is slightly see-through and fades
  further while you work in another app.
- 📋 **Auto-copy** — the finished translation is copied to your clipboard,
  ready to paste.
- 🌍 **16 languages + auto-detect** — English, Japanese, Chinese, Korean,
  Spanish, French, German, and [more](docs/usage.md#languages).
- 🎩 **Tone control** — Polite, Casual, Formal, Business, Friendly, Neutral, or
  your own custom instruction.
- 🔌 **OpenAI or Azure AI Foundry** — bring your own key and pick any model.

## Screenshots

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/images/hotkey.png" alt="Minimal window summoned with the hotkey, translating Japanese to English">
      <br><sub><b>Summon anywhere</b> — a minimal popup with ⇧⌘Space</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/images/languages.png" alt="Auto-detected English translated into Spanish with a Business tone">
      <br><sub><b>Pick a language and tone</b> — or let it auto-detect</sub>
    </td>
  </tr>
</table>

## Install

1. Download `Type-Fast-macos-arm64.zip` from the
   [latest release](https://github.com/wangx173/type-fast/releases/latest),
   unzip it, and drag **Type Fast.app** into `/Applications`. The prebuilt app
   requires an Apple Silicon Mac; on Intel Macs,
   [run from source](docs/development.md#run-from-source).
2. The app is ad-hoc signed, not notarized, so macOS blocks the first launch:
   - **macOS 15 and later:** open the app once, then go to **System Settings →
     Privacy & Security** and click **Open Anyway**.
   - **macOS 14 and earlier:** right-click the app → **Open** → **Open**.
3. Set your OpenAI API key in **Settings → Set OpenAI API Key…** (⌘,).

To use Azure AI Foundry instead, or to run from source, see
[Configuration](docs/configuration.md) and [Development](docs/development.md).

## Usage

Press **⇧⌘Space** in any app and type in the top box. The translation appears
below shortly after you pause, or right away when you end a sentence or press
Return. When it finishes, it is copied to the clipboard: press **⇧⌘Space** or
**Esc** to go back to your app, then **⌘V** to paste it.

| Shortcut                   | Action                                    |
|----------------------------|-------------------------------------------|
| **⇧⌘Space**                | Show or hide Type Fast from any app       |
| **Esc**                    | Hide the window                           |
| **⌘L**                     | Show the language and tone pickers        |
| **⌘,**                     | Set your OpenAI API key                   |

The **Settings** menu also lets you change the model, the hotkey, the window
transparency, and the custom tone. See the [usage guide](docs/usage.md) for
details.

## Documentation

| Guide                                    | What's inside                                            |
|------------------------------------------|----------------------------------------------------------|
| [Usage](docs/usage.md)                   | Window layouts, show/hide hotkey, languages, and tone    |
| [Configuration](docs/configuration.md)   | API keys, Azure AI Foundry, models, and saved settings   |
| [Development](docs/development.md)       | Run from source, run tests, and build the `.app`         |

## Roadmap

- Store the API key in the macOS Keychain instead of a key file.
- Sign and notarize the app with a Developer ID.
- A menu-bar wrapper (and hiding the Dock icon).

## License

[MIT](LICENSE) © Xiang Wang
