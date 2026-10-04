# Usage

- [The window](#the-window)
- [Show/hide hotkey](#showhide-hotkey)
- [Auto-paste](#auto-paste)
- [Transparency](#transparency)
- [Languages](#languages)
- [Tone](#tone)

## The window

The full window has:

- source and target language pickers with a **⇄** swap button,
- a tone selector,
- an input box and an output box that streams the translation, and
- the provider and model in use (for example **Azure · gpt-4.1-mini**; switch
  in **Settings → Provider**) and the show/hide hotkey, shown at the bottom.

Translation fires shortly after you stop typing, or immediately when your text
ends in sentence-ending punctuation (`.`, `!`, `?`, `。`, `！`, `？`, `؟`, `।`)
or you press Return. As you keep typing, finished lines are kept as they are and
only the line you are typing is sent for translation; changing the language,
tone, or model re-translates everything. When a translation finishes, it is
copied to the clipboard. Hide the window with the hotkey and it is
[pasted into your app](#auto-paste) for you.

The window is shown when the app launches. After that, summon and dismiss it
with the [show/hide hotkey](#showhide-hotkey) so it stays out of the way while
you are not using it.

## Show/hide hotkey

<img src="images/hotkey.png" alt="Minimal window summoned with the hotkey" width="460">

Like Spotlight, Type Fast pops up from any app with a global hotkey:
**⇧⌘Space** (Shift+Command+Space) by default.

- The window appears near the top of the screen the mouse pointer is on, stays
  on top, and puts the cursor in the input box. It opens empty each time; the
  last translation is still on the clipboard.
- Press the hotkey again to hide it, return to the app you were using, and
  [paste the translation](#auto-paste) there. **Esc** hides it without pasting.
  If you have clicked into another app while the window is still shown,
  the hotkey brings the window back to the front instead, showing the
  minimal layout.
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

The hotkey itself needs no Accessibility permission (only
[auto-paste](#auto-paste) does). It is saved to
`~/.type-fast/settings.json` as `"hotkey": "Shift+Cmd+Space"`; an empty string
disables it.

</details>

## Auto-paste

Hiding the window with the hotkey pastes the finished translation into the app
you return to, as if you had pressed **⌘V**. To go back without pasting, press
**Esc** instead. The translation is on the clipboard either way.

- It pastes only a finished translation, and only once. If you hide the window
  while a translation is still in progress, you open and hide it again without
  typing anything, or you copied something else in the meantime, nothing is
  pasted.
- Pasting into another app needs the **Accessibility** permission. If Type Fast
  doesn't have it, it tells you, at most once per launch, when you turn
  auto-paste on or when the hotkey would paste. Click **Open System Settings** and
  turn on Type Fast under **Privacy & Security → Accessibility** (add it with
  **+** if it isn't listed). No relaunch is needed. Until then, the hotkey just
  hides the window and you can paste with **⌘V** yourself.
- To turn it off, uncheck **Settings → Auto-Paste Translation**. The choice is
  saved to `~/.type-fast/settings.json` as `"auto_paste"`.

<details>
<summary>If auto-paste doesn't work</summary>

- **After updating Type Fast:** macOS may keep the old app's permission. In
  **Accessibility** settings, remove Type Fast with **−**, then allow it again.
- **Running from source:** the permission belongs to the app that runs Python,
  such as Terminal. Allowing it lets *every* program you run there send
  keystrokes to other apps, so prefer the
  [built app](development.md#build-the-macos-app) or paste with **⌘V**
  yourself. If you do allow your terminal, remove it from **Accessibility**
  when you are done.
- **Dvorak layouts:** auto-paste presses the key in the **V** position of a U.S.
  keyboard, which is a different key on Dvorak (it works on "Dvorak – QWERTY
  ⌘"). Turn auto-paste off and paste with **⌘V**.
- Some fields, such as password fields, may ignore the pasted text.

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
