---
type: bug
id: BUG-007
title: "The desktop app cannot use the AI: OPENAI_API_KEY is not found"
status: open
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-25
provenance: Created by an AI agent through MarkView
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
