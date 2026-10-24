---
type: bug
id: BUG-006
title: The alignment maps the photograph's markers to the plan's positions, so a file scaled to fit a smaller plate is measured beside its engraving
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-23
updated: 2026-10-24
provenance: Created by an AI agent through MarkView
---

# The alignment maps the photograph's markers to the plan's positions, so a file scaled to fit a smaller plate is measured beside its engraving

## Summary

Pair 116: the operator scaled the whole export, markers included, to a 153 × 153 mm plate (89% × 85%) and engraved that file. The ruler on the photograph puts the markers 143 mm apart, as the file has them, not 164 mm as the plan. The check still maps the markers to the plan's positions, stretches the photo space and draws the file's shapes without the stretch: contours beside the engraving, 120 of 158 vectors «found» by coincidence, 38 «uncertain», wrong colours, no warning. Supersedes BUG-005, which read the same pair wrongly (the file was the engraved one).

## Environment

Unknown

## Resolution

Fixed in 0.25.3 (64575b0): a file scaled or moved in LightBurn to the plate at hand, markers and cleaning rectangle
included, has the plan's marker geometry scaled to its size before the alignment, so its shapes are measured on the engraving in the
plate's millimetres; the file's size against the export is reported and warned about. Tests: `tests/test_scaled_file.py`.

Verified 2026-10-24 on 0.28.0: the tests named pass (70 passed), and the full suite passes (2015 passed, none skipped).
