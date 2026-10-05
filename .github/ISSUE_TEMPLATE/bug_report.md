---
name: Bug report
about: Something is broken or doesn't work as expected
title: ""
labels: bug
---

<!--
Write this so a person or an AI agent with no other context can fix it.
Only know what went wrong? Fill in Problem, Steps to reproduce, Expected
behavior, and Environment; a maintainer can add the rest.
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
- Installed from (release app or source):
- Provider (OpenAI or Azure AI Foundry):

## Logs or screenshots

<!--
Error messages or terminal output. This issue is public: first remove API keys
(anything like `sk-...`, `OPENAI_API_KEY`, `AZURE_AI_API_KEY`, files in
`~/.type-fast/`), your Foundry endpoint, and any private text you translated.
-->

## Out of scope

<!-- What the fix should NOT change. This tells the implementer where to stop. -->

-

## Acceptance criteria

<!-- What must be true when this is fixed. Each item should be checkable. -->

- [ ]
- [ ] A unit test covers the fix, where practical

## Verification

<!-- How to check the acceptance criteria. Hotkey, auto-paste, and Accessibility behavior need a manual check on a real Mac. -->

- [ ] `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v` passes
- [ ] Manual check on a real Mac, if needed (list the steps):

## Notes

<!-- Optional: likely cause, relevant files (for example `type_fast/autopaste.py`), related issues. -->
