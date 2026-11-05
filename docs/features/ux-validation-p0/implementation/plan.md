---
type: plan
feature: ux-validation-p0
title: UX redesign validation and domain guarantees
issues:
  - id: I-1
    title: Define the baseline and comparison protocol
    summary: Specify a repeatable before-and-after protocol covering work creation and continuation, color selection, lettering and photo zones, export and acceptance, and discrepancy investigation. Include first launch, import, interrupted entry, and recovery. Record task conditions, unassisted success, search and export time, backtracking, errors, repeated input, and lost changes. Label 20/200/2000 workloads as synthetic; select numerical targets only after baseline collection and keep hypotheses separate from observations.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Define runtime interaction and failure validation
    summary: Specify browser and Electron validation scenarios for multi-character search, focus and caret retention, double clicks, delayed and stale responses, save failures, recovery, and back navigation. Define setup, actions, expected behavior, and evidence to record for each scenario. Require actual-interface execution before acceptance; DOM simulation alone is insufficient.
    requirements: [REQ-002]
    decisions: []
  - id: I-3
    title: Specify accessibility and responsive-layout acceptance
    summary: Define keyboard and screen-reader checks and narrow-window, low-height-window, and enlarged-text scenarios, with explicit expected outcomes and result records. Identify tests coupled to exact CSS or column counts and document how they must align with approved layout requirements while preserving domain checks.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Specify image, palette, and asynchronous-state guarantees
    summary: Specify fixtures and acceptance scenarios proving that scale changes preserve the image, cards and predictions share the palette for the current width, and late responses cannot overwrite resize or undo state. Link scenarios to BUG-002 and BUG-011 and define observable evidence for each invariant without treating static code inspection as runtime proof.
    requirements: [REQ-003]
    decisions: []
  - id: I-5
    title: Specify domain and export integrity checks
    summary: Define acceptance checks for provenance and physical constraints, preview and LightBurn agreement, separate color and photo assessments, preservation of files and measurements, undo behavior, and explicit confirmation of complete re-segmentation. Document representative inputs, expected outcomes, and comparison evidence; record unresolved tolerances as open assumptions.
    requirements: [REQ-003]
    decisions: []
  - id: I-6
    title: Define legacy-document compatibility and validation review gates
    summary: Define a compatibility matrix for existing artwork, photo, and photo-preview documents, including unreachable colors and stripe processing. Require creation, reopening, and export checks with retained evidence before removing legacy screens. Consolidate protocol results into a review record that distinguishes observations, hypotheses, unresolved failures, and unexecuted checks; leave redesign proposals in draft until validation supports acceptance.
    requirements: [REQ-001, REQ-003]
    decisions: []
updated: 2026-11-05
---

# Implementation plan — [P0] Проверка пользы редизайна и предметных гарантий

## I-1: Define the baseline and comparison protocol

Specify a repeatable before-and-after protocol covering work creation and continuation, color selection, lettering and photo zones, export and acceptance, and discrepancy investigation. Include first launch, import, interrupted entry, and recovery. Record task conditions, unassisted success, search and export time, backtracking, errors, repeated input, and lost changes. Label 20/200/2000 workloads as synthetic; select numerical targets only after baseline collection and keep hypotheses separate from observations.

Requirements: REQ-001

## I-2: Define runtime interaction and failure validation

Specify browser and Electron validation scenarios for multi-character search, focus and caret retention, double clicks, delayed and stale responses, save failures, recovery, and back navigation. Define setup, actions, expected behavior, and evidence to record for each scenario. Require actual-interface execution before acceptance; DOM simulation alone is insufficient.

Requirements: REQ-002

## I-3: Specify accessibility and responsive-layout acceptance

Define keyboard and screen-reader checks and narrow-window, low-height-window, and enlarged-text scenarios, with explicit expected outcomes and result records. Identify tests coupled to exact CSS or column counts and document how they must align with approved layout requirements while preserving domain checks.

Requirements: REQ-002

## I-4: Specify image, palette, and asynchronous-state guarantees

Specify fixtures and acceptance scenarios proving that scale changes preserve the image, cards and predictions share the palette for the current width, and late responses cannot overwrite resize or undo state. Link scenarios to BUG-002 and BUG-011 and define observable evidence for each invariant without treating static code inspection as runtime proof.

Requirements: REQ-003

## I-5: Specify domain and export integrity checks

Define acceptance checks for provenance and physical constraints, preview and LightBurn agreement, separate color and photo assessments, preservation of files and measurements, undo behavior, and explicit confirmation of complete re-segmentation. Document representative inputs, expected outcomes, and comparison evidence; record unresolved tolerances as open assumptions.

Requirements: REQ-003

## I-6: Define legacy-document compatibility and validation review gates

Define a compatibility matrix for existing artwork, photo, and photo-preview documents, including unreachable colors and stripe processing. Require creation, reopening, and export checks with retained evidence before removing legacy screens. Consolidate protocol results into a review record that distinguishes observations, hypotheses, unresolved failures, and unexecuted checks; leave redesign proposals in draft until validation supports acceptance.

Requirements: REQ-001, REQ-003
