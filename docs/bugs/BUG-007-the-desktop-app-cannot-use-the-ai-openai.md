---
type: bug
id: BUG-007
title: "The desktop app cannot use the AI: OPENAI_API_KEY is not found"
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-25
provenance: Created by an AI agent through MarkView
updated: 2026-10-25
---

# The desktop app cannot use the AI: OPENAI_API_KEY is not found

## Summary

Under the desktop shell the core reads the language model key only from the environment, and an application opened from Finder has no OPENAI_API_KEY, so the AI researcher answers «OPENAI_API_KEY не найден в окружении или локальном .env.local» and every AI feature is off; there is no place in the application to give the key.

## Steps to reproduce

1. Open «Лазерная мастерская» 0.31.1 from Finder on the workshop ~/.titanium-platform
2. Open «AI-исследователь» and send a message (for example «Создай один следующий компактный LightBurn-тест для этой цели»)

## Expected

The AI answers; the key is kept by the workshop and can be entered and removed in the application.

## Actual

«OPENAI_API_KEY не найден в окружении или локальном .env.local»; research._api_key returns None when TCE_DESKTOP is set and the environment has no key.

## Environment

macOS arm64, desktop build 0.31.1 (packaged core, --desktop), workshop ~/.titanium-platform

## Resolution

Fixed in 0b29076, released in 0.32.0 (52de8f9; GitHub pre-release v0.32.0, macOS arm64 signed build).

- The workshop keeps its own key: `<workshop>/ai/openai.key` (folder 0700, file 0600), entered on «Сеть» → «Внешние службы» (`PUT /api/network/ai-key`); only its last four characters are ever shown. The environment's OPENAI_API_KEY still comes first; `.env.local` is read only outside the desktop shell.
- The key never goes into backups, diagnostics or laboratory releases.
- Tests: `tests/test_ui_network.py::test_the_openai_key_is_entered_on_the_network_screen_and_only_its_ending_is_shown` and the key tests of the research module; full suite 2214 passed, none skipped.
- Verified on this Mac: the key written to `~/.titanium-platform/ai/openai.key` (0600); `key_status` under `TCE_DESKTOP=1` reports source `workshop`. The packaged 0.32.0 passes its smoke (core 0.32.0, the interface draws).
- Open: the operator's own check in the 0.32.0 window (AI researcher answers) closes the bug.
