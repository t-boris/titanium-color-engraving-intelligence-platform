---
type: plan
feature: ux-save-feedback-p0
title: "P0: Reliable save feedback, recoverable operations, and accessible forms"
issues:
  - id: I-1
    title: Track document save state and reject stale responses
    summary: Define and implement document states for waiting, calculating, saving, saved, and failed. Tie save confirmation to the acknowledged revision so delayed responses cannot mark newer edits as saved or overwrite them. Apply the behavior to affected document workflows, including photo engraving, and verify overlapping edits with controlled response delays.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Preserve edits and provide persistent save-error recovery
    summary: Keep save errors beside the affected object until corrected or explicitly dismissed, preserve local input after failure, and provide retry while distinguishing local changes from confirmed server state. Ensure transient success notifications cannot hide an unresolved error. Verify failure, retry, dismissal, and a subsequent edit during retry.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Expose running operations across application navigation
    summary: Provide a shared operation registry and a task panel accessible from every section. Integrate upload, recheck, and import workflows so navigation does not remove access to their stage, available progress, result, recovery action, or originating context. Verify navigation away and return during execution; reload and application-restart persistence remain unspecified and must be recorded as an open scope question.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Define operation cancellation and recovery behavior
    summary: Separate closing the task panel from cancelling an operation. Establish cancellation and recovery behavior for each integrated operation using its actual backend capabilities, explain consequences before cancellation, and expose supported retry or recovery after failure. Verify that closing the panel leaves execution intact and that cancellation accurately reports any completed or retained work.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Make background-operation feedback accessible
    summary: Announce operation stage changes and terminal outcomes through accessible status messages without announcing each timer tick. Preserve visual progress and elapsed-time feedback, and make the task panel and its controls keyboard accessible with predictable focus behavior. Verify announcements with a screen reader during navigation, failure, retry, and completion.
    requirements: [REQ-002]
    decisions: []
  - id: I-6
    title: Standardize accessible field validation and retained input
    summary: Extend the shared field component and migrate affected forms to expose labels, requiredness, constraints, and persistent field errors through accessible associations. Map available server validation details to fields while retaining an actionable form-level error when attribution is unavailable. Preserve invalid input and verify correction and resubmission using keyboard and screen reader.
    requirements: [REQ-003]
    decisions: []
  - id: I-7
    title: Clarify quantity constraints and task-specific terminology
    summary: Audit affected forms and add explicit units and permitted ranges for dimensions, power, time, and other quantities, deriving constraints from documented domain and API rules. Record missing rules as open questions instead of inventing limits, and reject invalid values without silent correction. Explain pair, knowledge, stage, and basis in task-oriented language while keeping technical identifiers available in details.
    requirements: [REQ-003]
    decisions: []
  - id: I-8
    title: Verify recovery, accessibility, and domain guarantees end to end
    summary: Validate the integrated changes in the real browser and Electron interfaces using controlled failures, delayed responses, repeated actions, navigation, and return to saved work. Check keyboard access, screen-reader feedback, enlarged text, narrow screens, and low windows. Exercise the applicable n55–n58 workflows and domain guarantees, including preview/export consistency, palette consistency, cancellation restoration, and retained history; record observed results separately from assumptions and do not claim measured improvement without a baseline.
    requirements: [REQ-001, REQ-002, REQ-003]
    decisions: []
updated: 2026-11-05
---

# Implementation plan — [P0] Сохранение, ошибки, формы и фоновые задачи

## I-1: Track document save state and reject stale responses

Define and implement document states for waiting, calculating, saving, saved, and failed. Tie save confirmation to the acknowledged revision so delayed responses cannot mark newer edits as saved or overwrite them. Apply the behavior to affected document workflows, including photo engraving, and verify overlapping edits with controlled response delays.

Requirements: REQ-001

## I-2: Preserve edits and provide persistent save-error recovery

Keep save errors beside the affected object until corrected or explicitly dismissed, preserve local input after failure, and provide retry while distinguishing local changes from confirmed server state. Ensure transient success notifications cannot hide an unresolved error. Verify failure, retry, dismissal, and a subsequent edit during retry.

Requirements: REQ-001

## I-3: Expose running operations across application navigation

Provide a shared operation registry and a task panel accessible from every section. Integrate upload, recheck, and import workflows so navigation does not remove access to their stage, available progress, result, recovery action, or originating context. Verify navigation away and return during execution; reload and application-restart persistence remain unspecified and must be recorded as an open scope question.

Requirements: REQ-002

## I-4: Define operation cancellation and recovery behavior

Separate closing the task panel from cancelling an operation. Establish cancellation and recovery behavior for each integrated operation using its actual backend capabilities, explain consequences before cancellation, and expose supported retry or recovery after failure. Verify that closing the panel leaves execution intact and that cancellation accurately reports any completed or retained work.

Requirements: REQ-002

## I-5: Make background-operation feedback accessible

Announce operation stage changes and terminal outcomes through accessible status messages without announcing each timer tick. Preserve visual progress and elapsed-time feedback, and make the task panel and its controls keyboard accessible with predictable focus behavior. Verify announcements with a screen reader during navigation, failure, retry, and completion.

Requirements: REQ-002

## I-6: Standardize accessible field validation and retained input

Extend the shared field component and migrate affected forms to expose labels, requiredness, constraints, and persistent field errors through accessible associations. Map available server validation details to fields while retaining an actionable form-level error when attribution is unavailable. Preserve invalid input and verify correction and resubmission using keyboard and screen reader.

Requirements: REQ-003

## I-7: Clarify quantity constraints and task-specific terminology

Audit affected forms and add explicit units and permitted ranges for dimensions, power, time, and other quantities, deriving constraints from documented domain and API rules. Record missing rules as open questions instead of inventing limits, and reject invalid values without silent correction. Explain pair, knowledge, stage, and basis in task-oriented language while keeping technical identifiers available in details.

Requirements: REQ-003

## I-8: Verify recovery, accessibility, and domain guarantees end to end

Validate the integrated changes in the real browser and Electron interfaces using controlled failures, delayed responses, repeated actions, navigation, and return to saved work. Check keyboard access, screen-reader feedback, enlarged text, narrow screens, and low windows. Exercise the applicable n55–n58 workflows and domain guarantees, including preview/export consistency, palette consistency, cancellation restoration, and retained history; record observed results separately from assumptions and do not claim measured improvement without a baseline.

Requirements: REQ-001, REQ-002, REQ-003
