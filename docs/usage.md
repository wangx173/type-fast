# Usage

- [The window](#the-window)
- [Show/hide hotkey](#showhide-hotkey)
- [Transparency](#transparency)
- [Languages](#languages)
- [Tone](#tone)

## The window

The full window has:

- source and target language pickers with a **⇄** swap button,
- a tone selector,
- an input box and an output box that streams the translation, and
- the active model and the show/hide hotkey, shown at the bottom.

Translation fires shortly after you stop typing, or immediately when your text
ends in sentence-ending punctuation (`.`, `!`, `?`, `。`, `！`, `？`, `؟`, `।`)
or you press Return. As you keep typing, finished lines are kept as they are and
only the line you are typing is sent for translation; changing the language,
tone, or model re-translates everything. When a translation finishes, it is
copied to the clipboard.

The window is shown when the app launches. After that, summon and dismiss it
with the [show/hide hotkey](#showhide-hotkey) so it stays out of the way while
you are not using it.

## Show/hide hotkey

<img src="images/hotkey.png" alt="Minimal window summoned with the hotkey" width="460">

Like Spotlight, Type Fast pops up from any app with a global hotkey:
**⇧⌘Space** (Shift+Command+Space) by default.

- The window appears near the top of the screen under the mouse pointer, stays
  on top, and puts the cursor in the input box.
- Press the hotkey again, or **Esc**, to hide it and return to the app you were
  using.
- The current hotkey is shown at the bottom of the full window.

### Minimal layout

A window opened with the hotkey shows only the input and output boxes under a
one-line direction such as **English → Japanese**. Click the direction, or press
**⌘L** (**Settings → Show Language & Tone Options**), to show the pickers. When
the window opens any other way (at launch, from the Dock, or with ⌘Tab), it
shows the full layout.

### Change the hotkey

Choose **Settings → Set Show/Hide Hotkey…** and press the new combination.

- It must include ⌘ Command, ⌃ Control, or ⌥ Option. F-keys work on their own.
- **Reset to Default** restores ⇧⌘Space, and **Disable** turns the hotkey off.
- If macOS reserves a combination (such as ⌘Space or ⌘Tab), Type Fast tells you
  and keeps the previous one. Another app's global shortcut can't always be
  detected, so if the new hotkey does nothing, pick a different one.

<details>
<summary>Why ⇧⌘Space?</summary>

The default avoids the shortcuts macOS already uses for Space: ⌘Space and
⌥⌘Space (Spotlight), and ⌃Space and ⌃⌥Space (switching input sources). It also
avoids ⌥Space, which types a non-breaking space and is the default for
launchers such as Alfred, Raycast, and ChatGPT.

To use ⌘Space for Type Fast anyway, first change or turn off Spotlight's
shortcut in **System Settings → Keyboard → Keyboard Shortcuts → Spotlight**.

</details>

<details>
<summary>Keyboard layouts, permissions, and storage</summary>

Hotkeys are tied to the physical key you press, so they keep working if you
switch keyboard layouts. On non-U.S. layouts such as Dvorak or AZERTY, the key
is shown by its U.S. name (for example, the Dvorak "T" key appears as **K**).

The hotkey needs no Accessibility permission. It is saved to
`~/.type-fast/settings.json` as `"hotkey": "Shift+Cmd+Space"`; an empty string
disables it.

</details>

## Transparency

The window floats above your other apps, so by default it is slightly
see-through and doesn't fully hide what you are working on. You can turn this
off.

- It fades in when it appears.
- While you use it, it is almost opaque so the text stays easy to read.
- When you click into another app, it fades further so you can see the work
  behind it. Hover over it, or click it, to bring it back.

Choose how see-through it is in **Settings → Window Transparency**:

| Setting             | While in use | In the background |
|---------------------|--------------|-------------------|
| **Off**             | 100%         | 100%              |
| **Light** (default) | 95%          | 75%               |
| **Medium**          | 88%          | 60%               |
| **Strong**          | 80%          | 45%               |

The percentages are opacity. Your choice is saved to
`~/.type-fast/settings.json` as `"transparency"` and restored on launch.

## Languages

Choose the language you type in on the left and the language to translate into
on the right.

| Supported languages |                       |            |            |
|---------------------|-----------------------|------------|------------|
| English             | Chinese (Simplified)  | French     | Russian    |
| Japanese            | Chinese (Traditional) | German     | Vietnamese |
| Korean              | Spanish               | Italian    | Thai       |
| Indonesian          | Hindi                 | Portuguese | Arabic     |

- **Auto-detect** as the source lets the model work out the input language.
- **⇄** swaps the source and target. It is disabled while the source is
  Auto-detect.
- Picking the same language on both sides swaps the pair instead.
- Changing either language re-translates the current text.

The pair is saved to `~/.type-fast/settings.json` and restored on launch. To
add a language, add an entry to `LANGUAGES` in
[`type_fast/config.py`](../type_fast/config.py).

## Tone

Pick the tone of the translation from the selector next to the language
pickers:

| Tone                  | Style                                          |
|-----------------------|------------------------------------------------|
| **Polite** (default)  | Polite, courteous                              |
| **Casual**            | Relaxed and conversational, as between friends |
| **Formal**            | Suitable for official documents                |
| **Business**          | Professional, for work emails and meetings     |
| **Friendly**          | Warm and approachable                          |
| **Neutral**           | Mirrors the register of the original           |

Choose **Custom…**, or **Settings → Set Custom Tone…**, to write your own
instruction, such as "Humble keigo (謙譲語) for a client" or "Playful, with a
light touch of humor". The instruction is added to the translation prompt.

Changing the tone re-translates the current text. Your choice, and any custom
instruction, is saved to `~/.type-fast/settings.json` and restored on launch.
