---
type: plan
feature: ux-color-selection-p1
title: Unified measured-color selection across editing workflows
issues:
  - id: I-1
    title: Create the shared target-color selector
    summary: Create a shared color selector with visual selection and optional precise Lab input. Clearly distinguish the requested source color from measured titanium colors, and show the current source swatch. Review the component with keyboard navigation, visible focus, accessible labels, and text that conveys distinctions otherwise expressed through color.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Add image sampling and measured-recipe results
    summary: Connect image sampling to the shared selector so a sampled point displays its source swatch and corresponding eligible measured recipes. Define visible behavior when sampling is unavailable or no eligible recipes exist. Verify that sampling does not label the source swatch as a measured titanium result.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Integrate color selection across all four workflows
    summary: Integrate the shared selector into the map, brush, photo-point, and lettering workflows. Preserve each workflow's application semantics while exposing consistent visual selection, image sampling where an image is available, and precise Lab input. Verify all four integrations in the running interface, including keyboard operation and the distinction between target and measured colors.
    requirements: [REQ-001]
    decisions: []
  - id: I-4
    title: Implement measured-recipe comparison and sorting
    summary: Provide candidate comparison against the target swatch, displaying closeness, time, stability, and applicability to the selected equipment. Support sorting by closeness, time, and stability using documented project metrics. Explicitly represent unavailable values and define deterministic handling of missing values and ties before implementation; do not introduce unsupported stability estimates.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Unify recipe filters and preserve eligibility safeguards
    summary: Consolidate reliability and time filters into one clearly labeled group with visible and accessible active states. Preserve existing warnings and selection rules for unsuitable, revoked, and equipment-incompatible measurements across filtering, sorting, and selection. Verify applicable research guarantees n55–n58 against the running interface, including equipment changes and empty filtered results.
    requirements: [REQ-002]
    decisions: []
updated: 2026-11-06
---

# Implementation plan — [P1] Выбор измеренного цвета по образцу

## I-1: Create the shared target-color selector

Create a shared color selector with visual selection and optional precise Lab input. Clearly distinguish the requested source color from measured titanium colors, and show the current source swatch. Review the component with keyboard navigation, visible focus, accessible labels, and text that conveys distinctions otherwise expressed through color.

Requirements: REQ-001

## I-2: Add image sampling and measured-recipe results

Connect image sampling to the shared selector so a sampled point displays its source swatch and corresponding eligible measured recipes. Define visible behavior when sampling is unavailable or no eligible recipes exist. Verify that sampling does not label the source swatch as a measured titanium result.

Requirements: REQ-001

## I-3: Integrate color selection across all four workflows

Integrate the shared selector into the map, brush, photo-point, and lettering workflows. Preserve each workflow's application semantics while exposing consistent visual selection, image sampling where an image is available, and precise Lab input. Verify all four integrations in the running interface, including keyboard operation and the distinction between target and measured colors.

Requirements: REQ-001

## I-4: Implement measured-recipe comparison and sorting

Provide candidate comparison against the target swatch, displaying closeness, time, stability, and applicability to the selected equipment. Support sorting by closeness, time, and stability using documented project metrics. Explicitly represent unavailable values and define deterministic handling of missing values and ties before implementation; do not introduce unsupported stability estimates.

Requirements: REQ-002

## I-5: Unify recipe filters and preserve eligibility safeguards

Consolidate reliability and time filters into one clearly labeled group with visible and accessible active states. Preserve existing warnings and selection rules for unsuitable, revoked, and equipment-incompatible measurements across filtering, sorting, and selection. Verify applicable research guarantees n55–n58 against the running interface, including equipment changes and empty filtered results.

Requirements: REQ-002
