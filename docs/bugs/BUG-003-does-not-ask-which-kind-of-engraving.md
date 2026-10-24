---
type: bug
id: BUG-003
title: «Новая работа» does not ask which kind of engraving
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-22
updated: 2026-10-24
provenance: Created by an AI agent through MarkView
---

# «Новая работа» does not ask which kind of engraving

## Summary

In 0.21.0 the «Новая работа» dialog of photo engraving asked only for the picture, the name and the width. «Какая гравировка?» (REQ-071) opened only after «Создать», and the dialog announced it in one line of grey small print, so the operator, choosing «Новая работа», saw no question about the kind. Fixed in 0.21.1: the dialog has two steps, the picture and then which kind with the picture in each kind.

## Steps to reproduce

1. Open Фотогравировка → «Мои работы».
2. Click «Новая работа».
3. Look at the dialog: picture, name, width, «Отмена» and «Создать»; no choice of the kind.

## Expected

Choosing «Новая работа» asks which kind of engraving, with the picture shown in each kind, before the work is opened.

## Actual

The first dialog has no question about the kind; it opens only after «Создать» as a second dialog, which the operator did not expect from the first one.

## Environment

titanium-platform 0.21.0, port 8765, operator's data

## Resolution

Fixed in 0.21.1 (ffd3065): «Новая работа» asks which kind of engraving as its second step, with the picture in each kind
(REQ-071); «Назад» keeps the picture, and leaving the step deletes the work it made. Tests: `tests/test_photo_engraving_ui.py`.

Verified 2026-10-24 on 0.28.0: the tests named pass (70 passed), and the full suite passes (2015 passed, none skipped).
