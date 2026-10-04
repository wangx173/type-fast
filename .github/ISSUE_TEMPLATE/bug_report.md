---
name: Bug report
about: Something is broken or doesn't work as expected
title: ""
labels: bug
---

<!--
Write this so a person or an AI agent with no other context can fix it.
Delete sections that don't apply. Never paste API keys.
-->

## Problem

<!-- What goes wrong, in one or two sentences. -->

## Steps to reproduce

1.
2.
3.

## Expected behavior

<!-- What should happen instead. -->

## Environment

- macOS version:
- Type Fast version (release tag or commit):
- Installed from: release app / source
- Provider: OpenAI / Azure AI Foundry

## Logs or screenshots

<!-- Error messages or terminal output. Remove keys and personal text first. -->

## Acceptance criteria

<!-- Testable conditions that mean "fixed". -->

- [ ]
- [ ] A unit test covers the fix, where practical

## Verification

<!-- How to prove the fix. Hotkey, auto-paste, and Accessibility behavior need a manual check on a real Mac. -->

- [ ] `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v` passes
- [ ] Manual check on a real Mac:

## Notes

<!-- Optional: likely cause, relevant files (for example `type_fast/autopaste.py`), related issues, things not to change. -->
