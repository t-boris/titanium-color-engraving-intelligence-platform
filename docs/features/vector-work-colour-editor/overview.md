---
type: feature
id: vector-work-colour-editor
title: Vector work colour editor
status: implementing
owner: Boris Tsekinovsky
created: 2026-10-19
provenance: Created by an AI agent through MarkView from Operator request and answers, 2026-10-19 (after testing release 0.5.1 on work 22)
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: n/a
  Failure Scenarios: known
  Data Model: known
  Notifications: n/a
  Security: n/a
  Analytics: n/a
  Dependencies: known
  Acceptance Criteria: known
---

# Vector work colour editor

## Idea

The operator colours a photograph split into gapless regions (a vector work) with measured titanium colours before writing the LightBurn file. Today every colour outside a tiny ΔE tolerance waits for a separate "accept" click (28 clicks on a real work), and a colour can only be changed through a small picture and two nested dialogs. The operator needs a real editor: every colour assigned from the start, one large picture with a brush and a palette, click modes (one area, every area of a source colour, a fill over similar neighbours), merging (titanium colours into one, source colours into one, neighbouring areas into one contour), and undo/redo over all of it. Automatic recolouring modes stay as they are, for the whole work. Scope: the photograph strategy of a vector work only; the split itself, the palette, the time estimate and the export stay as built.

## Problem

## Scope
