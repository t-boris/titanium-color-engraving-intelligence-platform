---
type: plan
feature: feature-2
title: Titanium Business Card Design and Engraving Preparation
issues:
  - id: I-1
    title: Create and persist two-sided card work
    summary: Create a dedicated card work with 85 × 53 mm and 85 × 54 mm presets and custom dimensions. Provide physically sized front and back canvases, side switching, and save and reopen the complete editable work, including both sides, dimensions, elements, and engraving settings.
    requirements: [REQ-001]
    decisions: [DEC-028, DEC-029, DEC-032, DEC-036]
  - id: I-2
    title: Build card composition and element editing
    summary: Enable composition on either card side with lettering, a configurable library of shapes, frames, and icons, and imported graphics. Support independent selection, movement, resizing, rotation, layer reordering, duplication, and deletion for each supported element type.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-028, DEC-030, DEC-034]
  - id: I-3
    title: Generate card graphics with the OpenAI image service
    summary: Enable the operator to generate icons and drawings from descriptions with the OpenAI image service and add the results to either card side as images traced into engravable shapes. State the operating conditions (an internet connection, a configured API key and the workshop's AI switch on) and tell the operator which one is missing; the rest of the card workspace keeps working without a connection.
    requirements: [REQ-002]
    decisions: [DEC-030, DEC-039]
  - id: I-4
    title: Add a drawing treatment for card graphics
    summary: Allow the operator to apply a pencil-like drawing treatment to a graphic used on a card and see the treated result in the design before export.
    requirements: [REQ-004]
    decisions: []
  - id: I-5
    title: Generate and check card QR codes
    summary: Generate editable QR codes for links, vCards, text, Wi-Fi, email, and telephone content on either card side. Check module size and quiet zone at the placed physical size against separately defined thresholds, warn when either falls below its threshold, and allow preparation to continue; passing the check must not imply a scanning guarantee.
    requirements: [REQ-005]
    decisions: [DEC-031, DEC-034, DEC-038, DEC-040]
  - id: I-6
    title: Prepare and export card sides for engraving
    summary: Prepare each side separately for non-colour engraving, allowing the operator to assign and review different engraving settings for selected elements or groups. Export each side as a separate LightBurn project that preserves physical geometry and assigned settings for operator review.
    requirements: [REQ-003]
    decisions: [DEC-032, DEC-033, DEC-035]
updated: 2026-11-06
---

# Implementation plan — Гравировка титановых визиток

## I-1: Create and persist two-sided card work

Create a dedicated card work with 85 × 53 mm and 85 × 54 mm presets and custom dimensions. Provide physically sized front and back canvases, side switching, and save and reopen the complete editable work, including both sides, dimensions, elements, and engraving settings.

Requirements: REQ-001
Decisions: DEC-028, DEC-029, DEC-032, DEC-036

## I-2: Build card composition and element editing

Enable composition on either card side with lettering, a configurable library of shapes, frames, and icons, and imported graphics. Support independent selection, movement, resizing, rotation, layer reordering, duplication, and deletion for each supported element type.

Requirements: REQ-001, REQ-002
Decisions: DEC-028, DEC-030, DEC-034

## I-3: Generate card graphics with the OpenAI image service

Enable the operator to generate icons and drawings from descriptions with the OpenAI image service and add the results to either card side as images traced into engravable shapes. State the operating conditions (an internet connection, a configured API key and the workshop's AI switch on) and tell the operator which one is missing; the rest of the card workspace keeps working without a connection.

Requirements: REQ-002
Decisions: DEC-030, DEC-039

## I-4: Add a drawing treatment for card graphics

Allow the operator to apply a pencil-like drawing treatment to a graphic used on a card and see the treated result in the design before export.

Requirements: REQ-004

## I-5: Generate and check card QR codes

Generate editable QR codes for links, vCards, text, Wi-Fi, email, and telephone content on either card side. Check module size and quiet zone at the placed physical size against separately defined thresholds, warn when either falls below its threshold, and allow preparation to continue; passing the check must not imply a scanning guarantee.

Requirements: REQ-005
Decisions: DEC-031, DEC-034, DEC-038, DEC-040

## I-6: Prepare and export card sides for engraving

Prepare each side separately for non-colour engraving, allowing the operator to assign and review different engraving settings for selected elements or groups. Export each side as a separate LightBurn project that preserves physical geometry and assigned settings for operator review.

Requirements: REQ-003
Decisions: DEC-032, DEC-033, DEC-035
