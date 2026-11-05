---
type: plan
feature: ux-accessible-layout-p0
title: Accessible keyboard workflows and adaptive workspace layouts
issues:
  - id: I-1
    title: Complete the primary keyboard workflow
    summary: Enable the menu → search → dialog → color → editor → export → return workflow using only the keyboard, with visible focus and a logical navigation order. Preserve tab semantics and coordinate with the separate dialog, skip-link, and font bug fixes without duplicating their scope.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Add keyboard-accessible alternatives to canvas interactions
    summary: Provide an accessible object list and numeric fields or buttons for object selection, movement, rotation, and zoom. Ensure these controls can be operated with the keyboard and provide alternatives to gestures and small canvas handles.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Adapt the workspace to narrow viewports
    summary: Adapt panels and forms to a viewport width of 320 CSS px while keeping information and primary actions accessible. Show selected-object properties in a slide-out panel, keep the header from displacing the usable work area, and allow separate scrolling for the two-dimensional canvas where necessary.
    requirements: [REQ-002]
    decisions: [DEC-001]
  - id: I-4
    title: Support low windows and enlarged text
    summary: Keep form controls and save/export actions reachable and usable in an 800×600 CSS px content viewport, with text enlarged to 200%, and with both conditions combined. Permit vertical form scrolling and ensure layout changes preserve access to the keyboard workflow.
    requirements: [REQ-002]
    decisions: [DEC-001]
  - id: I-5
    title: Verify accessibility profiles and domain guarantees
    summary: Verify the actual interface in the browser and Electron across the required viewport and text-size profiles. Record keyboard workflow results, visible focus, tab semantics, reduced motion, system contrast modes, and actual target sizes and spacing. Verify preservation of images during scale changes, matching card and prediction palettes for the current width, stale-response rejection, cancellation restoring size and settings, preview/export consistency, independent color and photoengraving assessments, and file and measurement history. Record runtime evidence; CSS declarations alone do not establish acceptance.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
updated: 2026-11-05
---

# Implementation plan — [P0] Клавиатура, холст и небольшое окно

## I-1: Complete the primary keyboard workflow

Enable the menu → search → dialog → color → editor → export → return workflow using only the keyboard, with visible focus and a logical navigation order. Preserve tab semantics and coordinate with the separate dialog, skip-link, and font bug fixes without duplicating their scope.

Requirements: REQ-001

## I-2: Add keyboard-accessible alternatives to canvas interactions

Provide an accessible object list and numeric fields or buttons for object selection, movement, rotation, and zoom. Ensure these controls can be operated with the keyboard and provide alternatives to gestures and small canvas handles.

Requirements: REQ-001

## I-3: Adapt the workspace to narrow viewports

Adapt panels and forms to a viewport width of 320 CSS px while keeping information and primary actions accessible. Show selected-object properties in a slide-out panel, keep the header from displacing the usable work area, and allow separate scrolling for the two-dimensional canvas where necessary.

Requirements: REQ-002
Decisions: DEC-001

## I-4: Support low windows and enlarged text

Keep form controls and save/export actions reachable and usable in an 800×600 CSS px content viewport, with text enlarged to 200%, and with both conditions combined. Permit vertical form scrolling and ensure layout changes preserve access to the keyboard workflow.

Requirements: REQ-002
Decisions: DEC-001

## I-5: Verify accessibility profiles and domain guarantees

Verify the actual interface in the browser and Electron across the required viewport and text-size profiles. Record keyboard workflow results, visible focus, tab semantics, reduced motion, system contrast modes, and actual target sizes and spacing. Verify preservation of images during scale changes, matching card and prediction palettes for the current width, stale-response rejection, cancellation restoring size and settings, preview/export consistency, independent color and photoengraving assessments, and file and measurement history. Record runtime evidence; CSS declarations alone do not establish acceptance.

Requirements: REQ-001, REQ-002
Decisions: DEC-001
