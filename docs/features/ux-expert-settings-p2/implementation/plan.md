---
type: plan
feature: ux-expert-settings-p2
title: "Expert settings: density, technical information, and calibration"
issues:
  - id: I-1
    title: Implement readable density modes
    summary: Implement normal and compact density modes with readable labels, access to complete names without hover, clear semantic groups, and reduced decorative noise. Verify that errors remain visible and touch targets remain usable in both modes, including with keyboard navigation, text enlargement, narrow and low windows, and tablet interaction.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Evaluate the light theme in workshop conditions
    summary: Prepare current and light theme variants for comparison, then evaluate readability and task performance under actual workshop lighting and on a tablet. Record the methods and results for a later release decision; the comparison does not itself authorize release of the light theme.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-3
    title: Build the reference calibration grid
    summary: Replace manual JSON editing of custom reference values with a 24-patch grid containing labeled L, a, and b fields and an explicit traversal order. Validate each triplet with errors identifying the row and field, and verify that invalid input can be corrected without losing entered values.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Support reference data exchange and restoration
    summary: Provide secondary import and export actions for raw reference numbers, show the reference set, its source, and white point, and allow restoration of published values. Verify that restoring or changing reference values does not silently alter previously accepted measurements.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Group equipment technical information
    summary: Group equipment charts, pulse waveforms, the test report, and documents under clearly named technical information groups while keeping frequent equipment actions visible. Verify that all existing information and actions remain reachable, including by keyboard, and check the grouping against representative operator tasks.
    requirements: [REQ-003]
    decisions: [DEC-001]
  - id: I-6
    title: Verify integrated workflows and domain guarantees
    summary: Review the completed changes in the real browser and Electron interfaces using relevant end-to-end tasks, accessibility checks, and before-and-after observations from research nodes n55–n57. Check the applicable domain guarantees in n58, including preservation of measurement and file history and consistency between preview and export; record outcomes and any unresolved regressions without claiming an improvement solely from fewer controls.
    requirements: [REQ-001, REQ-002, REQ-003]
    decisions: []
updated: 2026-11-06
---

# Implementation plan — [P2] Плотность, технические справки и калибровка

## I-1: Implement readable density modes

Implement normal and compact density modes with readable labels, access to complete names without hover, clear semantic groups, and reduced decorative noise. Verify that errors remain visible and touch targets remain usable in both modes, including with keyboard navigation, text enlargement, narrow and low windows, and tablet interaction.

Requirements: REQ-001

## I-2: Evaluate the light theme in workshop conditions

Prepare current and light theme variants for comparison, then evaluate readability and task performance under actual workshop lighting and on a tablet. Record the methods and results for a later release decision; the comparison does not itself authorize release of the light theme.

Requirements: REQ-001
Decisions: DEC-001

## I-3: Build the reference calibration grid

Replace manual JSON editing of custom reference values with a 24-patch grid containing labeled L, a, and b fields and an explicit traversal order. Validate each triplet with errors identifying the row and field, and verify that invalid input can be corrected without losing entered values.

Requirements: REQ-002

## I-4: Support reference data exchange and restoration

Provide secondary import and export actions for raw reference numbers, show the reference set, its source, and white point, and allow restoration of published values. Verify that restoring or changing reference values does not silently alter previously accepted measurements.

Requirements: REQ-002

## I-5: Group equipment technical information

Group equipment charts, pulse waveforms, the test report, and documents under clearly named technical information groups while keeping frequent equipment actions visible. Verify that all existing information and actions remain reachable, including by keyboard, and check the grouping against representative operator tasks.

Requirements: REQ-003
Decisions: DEC-001

## I-6: Verify integrated workflows and domain guarantees

Review the completed changes in the real browser and Electron interfaces using relevant end-to-end tasks, accessibility checks, and before-and-after observations from research nodes n55–n57. Check the applicable domain guarantees in n58, including preservation of measurement and file history and consistency between preview and export; record outcomes and any unresolved regressions without claiming an improvement solely from fewer controls.

Requirements: REQ-001, REQ-002, REQ-003
