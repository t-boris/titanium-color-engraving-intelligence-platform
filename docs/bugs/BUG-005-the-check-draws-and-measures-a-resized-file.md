---
type: bug
id: BUG-005
title: The check draws and measures a resized file at its own size although the photograph's markers show the engraving at the export's size
status: open
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-23
provenance: Created by an AI agent through MarkView
---

# The check draws and measures a resized file at its own size although the photograph's markers show the engraving at the export's size

## Summary

Pair 116: the loaded file is export 5 scaled to 89% × 85%, markers included; the plate was engraved at the export's size. The check aligns by the plan's markers, never compares them with the file's own Markers layer, and measures shrunken contours beside the engraving: 120 of 158 vectors «found» by coincidence, 38 «uncertain», no warning.

## Environment

Unknown
