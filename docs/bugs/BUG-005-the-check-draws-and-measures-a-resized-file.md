---
type: bug
id: BUG-005
title: The check draws and measures a resized file at its own size although the photograph's markers show the engraving at the export's size
status: closed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-23
updated: 2026-10-24
provenance: Created by an AI agent through MarkView
---

# The check draws and measures a resized file at its own size although the photograph's markers show the engraving at the export's size

## Summary

Pair 116: the loaded file is export 5 scaled to 89% × 85%, markers included; the plate was engraved at the export's size. The check aligns by the plan's markers, never compares them with the file's own Markers layer, and measures shrunken contours beside the engraving: 120 of 158 vectors «found» by coincidence, 38 «uncertain», no warning.

## Environment

Unknown

## Resolution

Closed as a duplicate of BUG-006, not fixed on its own: it read pair 116 wrongly (the loaded file was the one engraved,
scaled with its markers to a smaller plate). The real defect is the alignment to the plan's marker positions, reported and fixed as
BUG-006 (reported in aac182b, fixed in 0.25.3 by 64575b0).
