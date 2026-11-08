---
type: plan
feature: feature-3
title: Import and edit vector artwork in business-card designs
issues:
  - id: I-1
    title: Import vector files as editable artwork
    summary: Add device-file selection and import for SVG and Adobe Illustrator artwork on the active card side. Convert supported content into individually editable parts while preserving supported appearance and source colours. Define and document the supported content and file variants; report failed imports and any content that cannot be preserved without presenting an incomplete result as complete.
    requirements: [REQ-003]
    decisions: [DEC-001, DEC-002]
  - id: I-2
    title: Compose card designs with imported parts
    summary: Integrate imported parts with the canvas and existing element actions so operators can select, move, resize, rotate, duplicate, reorder, group, ungroup and delete them. Preserve independent editing of parts without exposing path-node editing.
    requirements: [REQ-003, REQ-005]
    decisions: [DEC-001]
  - id: I-3
    title: Edit design colours and select engraving colours
    summary: Allow individual imported parts to be recoloured and retain their source colours as design colours. Distinguish design colours from engraving selections, suggest available engraving colours for source colours, allow the operator to change the selection and indicate when no match is available.
    requirements: [REQ-003, REQ-004]
    decisions: [DEC-001, DEC-002]
  - id: I-4
    title: Save and reopen editable imported artwork
    summary: Persist imported parts, their geometry and edits, design colours and engraving selections with the card work. Verify that saving and reopening restores them on the correct card side for continued editing.
    requirements: [REQ-005]
    decisions: [DEC-001, DEC-002]
  - id: I-5
    title: Apply selected engraving colours to preparation and export
    summary: Use the operator's selected engraving colours when preparing and exporting each card side for colour engraving. Verify that selections associated with imported parts survive the preparation and export workflow and remain distinct from design colours.
    requirements: [REQ-004, REQ-005]
    decisions: [DEC-002, DEC-003]
updated: 2026-11-08
---

# Implementation plan — Импорт и редактирование векторов для бизнес-карточки

## I-1: Import vector files as editable artwork

Add device-file selection and import for SVG and Adobe Illustrator artwork on the active card side. Convert supported content into individually editable parts while preserving supported appearance and source colours. Define and document the supported content and file variants; report failed imports and any content that cannot be preserved without presenting an incomplete result as complete.

Requirements: REQ-003
Decisions: DEC-001, DEC-002

## I-2: Compose card designs with imported parts

Integrate imported parts with the canvas and existing element actions so operators can select, move, resize, rotate, duplicate, reorder, group, ungroup and delete them. Preserve independent editing of parts without exposing path-node editing.

Requirements: REQ-003, REQ-005
Decisions: DEC-001

## I-3: Edit design colours and select engraving colours

Allow individual imported parts to be recoloured and retain their source colours as design colours. Distinguish design colours from engraving selections, suggest available engraving colours for source colours, allow the operator to change the selection and indicate when no match is available.

Requirements: REQ-003, REQ-004
Decisions: DEC-001, DEC-002

## I-4: Save and reopen editable imported artwork

Persist imported parts, their geometry and edits, design colours and engraving selections with the card work. Verify that saving and reopening restores them on the correct card side for continued editing.

Requirements: REQ-005
Decisions: DEC-001, DEC-002

## I-5: Apply selected engraving colours to preparation and export

Use the operator's selected engraving colours when preparing and exporting each card side for colour engraving. Verify that selections associated with imported parts survive the preparation and export workflow and remain distinct from design colours.

Requirements: REQ-004, REQ-005
Decisions: DEC-002, DEC-003
