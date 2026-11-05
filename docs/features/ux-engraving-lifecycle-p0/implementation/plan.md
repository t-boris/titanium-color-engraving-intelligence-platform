---
type: plan
feature: ux-engraving-lifecycle-p0
title: "[P0] Export and compare results for a specific engraving"
issues:
  - id: I-1
    title: Preserve export versions and engraving prediction provenance
    summary: Preserve the association between each exported file, its document version, its saved prediction and its engraving results across edits, repeat exports and reopening. Reuse existing history mechanisms where available. Keep the current document and recalculated prediction distinct from historical exports; identify missing historical predictions explicitly and never substitute a reconstruction as the original promise. Verify that accepting new measurements preserves existing file and result associations.
    requirements: [REQ-002, REQ-003]
    decisions: []
  - id: I-2
    title: Unify export readiness, blockers and file download
    summary: Provide a consistent “Download LightBurn” action with dimensions, estimated duration, layer count, readiness and reasons for restrictions before download. Link blockers to the affected region or missing data, and expose the complete recipe and previous files through progressive disclosure. Allow download without a mandatory intermediate plan screen while retaining color reachability, layer and cleanup checks. Preserve local file download behavior without sending files to the laser, and verify recoverable download failures.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Connect lifecycle stages and return users to the originating work
    summary: Show the Prepared → File obtained → Result added → Verified sequence in work and experiment contexts, with the action appropriate to the current stage. Derive progression from recorded events associated with the relevant export and result, so a repeat export or edit cannot inherit verification from another version. After photo acceptance, return to the originating work with a concise summary of current prediction changes and the next available action. Verify progression after reopening and after interrupted or failed operations.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Compare a selected engraving against its saved expectation
    summary: Provide an engraving selector and an Expected / Actual comparison using the selected engraving’s saved prediction and result photo at the same scale, highlighting the largest differences. Clearly identify the comparison basis and distinguish any prediction reconstructed from earlier measurements from a prediction saved with the exported file. Present changes to the current prediction separately, preserve independent color and photo evaluations, and retain undo for current-color replacement. Verify selection changes, missing comparison data and acceptance of new measurements.
    requirements: [REQ-003]
    decisions: []
  - id: I-5
    title: Verify lifecycle accessibility, compatibility and domain guarantees
    summary: Validate the complete download, result acceptance and comparison journey in the browser and Electron, including keyboard and screen-reader use, enlarged text, narrow and low windows, repeated clicks, delayed responses and recovery from failures. Check creation, reopening and export of existing document types before consolidating legacy entry points. Confirm preview/export consistency, preserved histories, independent evaluations and undo behavior. Record task success, time to download, returns and mistaken actions before and after changes; report observations without inventing numerical targets or claiming unmeasured improvement.
    requirements: [REQ-001, REQ-002, REQ-003]
    decisions: []
updated: 2026-11-05
---

# Implementation plan — [P0] Экспорт и сравнение с конкретной гравировкой

## I-1: Preserve export versions and engraving prediction provenance

Preserve the association between each exported file, its document version, its saved prediction and its engraving results across edits, repeat exports and reopening. Reuse existing history mechanisms where available. Keep the current document and recalculated prediction distinct from historical exports; identify missing historical predictions explicitly and never substitute a reconstruction as the original promise. Verify that accepting new measurements preserves existing file and result associations.

Requirements: REQ-002, REQ-003

## I-2: Unify export readiness, blockers and file download

Provide a consistent “Download LightBurn” action with dimensions, estimated duration, layer count, readiness and reasons for restrictions before download. Link blockers to the affected region or missing data, and expose the complete recipe and previous files through progressive disclosure. Allow download without a mandatory intermediate plan screen while retaining color reachability, layer and cleanup checks. Preserve local file download behavior without sending files to the laser, and verify recoverable download failures.

Requirements: REQ-001

## I-3: Connect lifecycle stages and return users to the originating work

Show the Prepared → File obtained → Result added → Verified sequence in work and experiment contexts, with the action appropriate to the current stage. Derive progression from recorded events associated with the relevant export and result, so a repeat export or edit cannot inherit verification from another version. After photo acceptance, return to the originating work with a concise summary of current prediction changes and the next available action. Verify progression after reopening and after interrupted or failed operations.

Requirements: REQ-002

## I-4: Compare a selected engraving against its saved expectation

Provide an engraving selector and an Expected / Actual comparison using the selected engraving’s saved prediction and result photo at the same scale, highlighting the largest differences. Clearly identify the comparison basis and distinguish any prediction reconstructed from earlier measurements from a prediction saved with the exported file. Present changes to the current prediction separately, preserve independent color and photo evaluations, and retain undo for current-color replacement. Verify selection changes, missing comparison data and acceptance of new measurements.

Requirements: REQ-003

## I-5: Verify lifecycle accessibility, compatibility and domain guarantees

Validate the complete download, result acceptance and comparison journey in the browser and Electron, including keyboard and screen-reader use, enlarged text, narrow and low windows, repeated clicks, delayed responses and recovery from failures. Check creation, reopening and export of existing document types before consolidating legacy entry points. Confirm preview/export consistency, preserved histories, independent evaluations and undo behavior. Record task success, time to download, returns and mistaken actions before and after changes; report observations without inventing numerical targets or claiming unmeasured improvement.

Requirements: REQ-001, REQ-002, REQ-003
