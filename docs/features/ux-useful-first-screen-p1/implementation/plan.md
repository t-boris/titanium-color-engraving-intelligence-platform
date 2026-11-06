---
type: plan
feature: ux-useful-first-screen-p1
title: Useful First Screen Without Waiting for Secondary Content
issues:
  - id: I-1
    title: Decouple primary content from secondary requests
    summary: Render the primary experiment catalogue or document as soon as its required local data is available. Load secondary conclusions, photo knowledge and task guidance independently, with section-local loading, error and retry states. Verify that delayed or failed secondary requests leave available local work usable and that responses arriving after navigation cannot update another screen.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Load hidden laboratory tabs on demand
    summary: Load laboratory tabs, including the cloud catalogue, when first opened instead of awaiting all tabs before displaying the screen. Give each tab its own loading, error and retry states. Verify that opening local work does not request hidden-tab data, repeated activation avoids duplicate in-flight requests, and cloud failures do not block local operations.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Preserve and label the previous prediction during recalculation
    summary: Keep the last successful prediction visible during recalculation and identify it visibly and accessibly as a previous result awaiting an update. Preserve the image on calculation failure and offer recovery alongside the error. Distinguish initial calculation without a previous result, pending recalculation, failure and successful replacement; status updates must preserve keyboard focus.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Prevent stale prediction responses from replacing current state
    summary: Ensure that only a response matching the current document, settings and calculation request can replace the displayed prediction or its status. Cover rapid setting changes, scale changes, cancellation, navigation and responses arriving out of order. Verify that stale successes and failures cannot overwrite a newer result, clear the retained image or restore cancelled settings.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Reuse existing thumbnails and cached renders
    summary: Use existing thumbnails and render-cache paths for repeated image display, retaining invalidation when relevant source data or rendering settings change. Verify cache reuse and RAW decoding behavior for initial display, repeated display and recalculation. Treat BUG-001 as fixed regression context; reopening it requires a new measurement demonstrating a current defect.
    requirements: [REQ-002]
    decisions: []
  - id: I-6
    title: Measure first useful display and verify real-interface regressions
    summary: "Before implementation, record a reproducible baseline and define the observable point at which the primary catalogue or document becomes usable. Repeat measurements after implementation on the same datasets and environment, separating cold and warm cache results without inventing an SLA. Validate affected workflows in the real browser and Electron interface with delayed and failed requests, keyboard and screen-reader operation, enlarged text and constrained viewports. Record results and failures, checking the applicable n55–n58 guarantees: retained images on scale changes, palette consistency, cancellation, preview/export agreement, separate color and photo-engraving assessments, and preserved file and measurement history."
    requirements: [REQ-001, REQ-002]
    decisions: []
updated: 2026-11-06
---

# Implementation plan — [P1] Первый полезный экран без ожидания скрытых вкладок

## I-1: Decouple primary content from secondary requests

Render the primary experiment catalogue or document as soon as its required local data is available. Load secondary conclusions, photo knowledge and task guidance independently, with section-local loading, error and retry states. Verify that delayed or failed secondary requests leave available local work usable and that responses arriving after navigation cannot update another screen.

Requirements: REQ-001

## I-2: Load hidden laboratory tabs on demand

Load laboratory tabs, including the cloud catalogue, when first opened instead of awaiting all tabs before displaying the screen. Give each tab its own loading, error and retry states. Verify that opening local work does not request hidden-tab data, repeated activation avoids duplicate in-flight requests, and cloud failures do not block local operations.

Requirements: REQ-001

## I-3: Preserve and label the previous prediction during recalculation

Keep the last successful prediction visible during recalculation and identify it visibly and accessibly as a previous result awaiting an update. Preserve the image on calculation failure and offer recovery alongside the error. Distinguish initial calculation without a previous result, pending recalculation, failure and successful replacement; status updates must preserve keyboard focus.

Requirements: REQ-002

## I-4: Prevent stale prediction responses from replacing current state

Ensure that only a response matching the current document, settings and calculation request can replace the displayed prediction or its status. Cover rapid setting changes, scale changes, cancellation, navigation and responses arriving out of order. Verify that stale successes and failures cannot overwrite a newer result, clear the retained image or restore cancelled settings.

Requirements: REQ-002

## I-5: Reuse existing thumbnails and cached renders

Use existing thumbnails and render-cache paths for repeated image display, retaining invalidation when relevant source data or rendering settings change. Verify cache reuse and RAW decoding behavior for initial display, repeated display and recalculation. Treat BUG-001 as fixed regression context; reopening it requires a new measurement demonstrating a current defect.

Requirements: REQ-002

## I-6: Measure first useful display and verify real-interface regressions

Before implementation, record a reproducible baseline and define the observable point at which the primary catalogue or document becomes usable. Repeat measurements after implementation on the same datasets and environment, separating cold and warm cache results without inventing an SLA. Validate affected workflows in the real browser and Electron interface with delayed and failed requests, keyboard and screen-reader operation, enlarged text and constrained viewports. Record results and failures, checking the applicable n55–n58 guarantees: retained images on scale changes, palette consistency, cancellation, preview/export agreement, separate color and photo-engraving assessments, and preserved file and measurement history.

Requirements: REQ-001, REQ-002
