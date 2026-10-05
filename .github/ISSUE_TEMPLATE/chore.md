---
name: Chore
about: Work that isn't a bug fix or a new feature, such as docs, maintenance, refactoring, or an investigation
title: ""
labels: chore
---

<!--
Write this so a person or an AI agent with no other context can do it.
Delete sections that don't apply.
-->

## Goal

<!-- What needs to be done, and why. -->

## Scope

<!-- What this issue should change. -->

-

## Out of scope

<!-- What this issue should NOT change. This tells the implementer where to stop. -->

-

## Acceptance criteria

<!-- What must be true when this is done. Each item should be checkable. For an investigation, say what the result should be (for example, a summary comment or a doc). -->

- [ ]

## Verification

<!-- How to check the acceptance criteria. Delete the lines that don't apply. -->

- [ ] `QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v` passes, if code changed
- [ ] Manual check on a real Mac, if hotkey, auto-paste, Accessibility, or UI code changed (list the steps):
- [ ] Links in changed docs work, if docs changed

## Notes

<!-- Optional: relevant files, docs, related issues, or examples. -->
