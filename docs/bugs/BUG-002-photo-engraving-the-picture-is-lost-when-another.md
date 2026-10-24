---
type: bug
id: BUG-002
title: "Photo engraving: the picture is lost when another scale is chosen"
status: fixed
severity: medium
reporter: Boris Tsekinovsky
created: 2026-10-22
updated: 2026-10-24
provenance: Created by an AI agent through MarkView
---

# Photo engraving: the picture is lost when another scale is chosen

## Summary

On the Фотогравировка screen, choosing another measured scale rebuilt the whole scale panel, and with it the "Картинка на этой шкале" block: the chosen file, width, colour choice and the prediction disappeared, and the operator had to choose the picture again for every scale. Fixed in 0.18.2: one picture block serves the whole screen, the picture stays when the scale changes and is predicted on the new scale by itself; the prediction also follows the file, width, Min/Max and the colour choice without pressing the button.

## Steps to reproduce

1. Open Фотогравировка (#/photo-engraving) with at least two measured scales
2. In 'Картинка на этой шкале' choose a picture and press 'Показать на титане'
3. Click another scale in 'Измеренные шкалы'

## Expected

The same picture stays chosen and its predicted look is redrawn for the new scale (its Min and Max) without choosing the file again.

## Actual

The picture block is rebuilt empty: 'Файл не выбран', no prediction; the file has to be chosen again.

## Environment

Лазерная мастерская 0.18.1, operator's app on 127.0.0.1:8765; reported by the operator 2026-10-22 ("когда я выбираю картинку, а потом меняю шкалу, то он картинку удаляет")

## Resolution

Fixed in 0.18.2 (09d34c1): one picture block serves the whole screen; the picture stays when another scale is chosen and
its prediction follows the scale, Min/Max, the width and the colour choice by itself. Tests: `tests/test_photo_engraving_ui.py`.

Verified 2026-10-24 on 0.28.0: the tests named pass (70 passed), and the full suite passes (2015 passed, none skipped).
