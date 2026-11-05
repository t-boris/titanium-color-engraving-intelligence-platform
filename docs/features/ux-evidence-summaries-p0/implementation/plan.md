---
type: plan
feature: ux-evidence-summaries-p0
title: Concise Evidence Summaries and Finding Decision Queue
issues:
  - id: I-1
    title: Present independent evidence signals in a concise summary
    summary: Add a first-level evidence summary that distinguishes repeated verification, a single result, and disagreement while keeping measurement source and basis independently visible. Preserve separate color and photo assessments, and expose Lab, ΔE, and full sources through disclosure.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Expose forecast applicability and preserve prediction safeguards
    summary: Show prediction applicability above the forecast, distinguishing measurements at the current size, measurements at another width, and test-scale evidence only. Preserve unknown-region hatching and the actual power range, and verify that the displayed category follows the available evidence.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Introduce finding rows with a cause-checking recommendation
    summary: Present each finding with its problem, affected work or context, and one recommended next action. Recommend photograph remeasurement for measurement anomalies when available; open supporting evidence when the corrective choice is ambiguous. Apply the same queue principle to photo findings and retain other available remedies through disclosure without changing eligibility, consequence previews, confirmations, or restrictions on historical runs.
    requirements: [REQ-002]
    decisions: [DEC-001]
  - id: I-4
    title: Preserve queue controls and secondary workflows
    summary: Integrate existing attention and acknowledged states, hiding until substantive changes, notes, and pinning into the decision queue. Preserve the existing rules for returning findings to attention after new measurements change their substance. Keep calculation history, scheduling, and exclusions accessible through secondary disclosure.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Validate usability, accessibility, and domain guarantees
    summary: Validate the combined flow in the real browser and Electron interfaces, including discrepancy investigation, keyboard and screen-reader access, enlarged text, narrow screens, and action failures. Compare task completion, time, and erroneous actions before and after the changes. Verify the applicable n55–n58 domain guarantees, document observed results separately from expected benefits, and record unresolved acceptance gaps.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
updated: 2026-11-05
---

# Implementation plan — [P0] Краткая достоверность и очередь решений

## I-1: Present independent evidence signals in a concise summary

Add a first-level evidence summary that distinguishes repeated verification, a single result, and disagreement while keeping measurement source and basis independently visible. Preserve separate color and photo assessments, and expose Lab, ΔE, and full sources through disclosure.

Requirements: REQ-001

## I-2: Expose forecast applicability and preserve prediction safeguards

Show prediction applicability above the forecast, distinguishing measurements at the current size, measurements at another width, and test-scale evidence only. Preserve unknown-region hatching and the actual power range, and verify that the displayed category follows the available evidence.

Requirements: REQ-001

## I-3: Introduce finding rows with a cause-checking recommendation

Present each finding with its problem, affected work or context, and one recommended next action. Recommend photograph remeasurement for measurement anomalies when available; open supporting evidence when the corrective choice is ambiguous. Apply the same queue principle to photo findings and retain other available remedies through disclosure without changing eligibility, consequence previews, confirmations, or restrictions on historical runs.

Requirements: REQ-002
Decisions: DEC-001

## I-4: Preserve queue controls and secondary workflows

Integrate existing attention and acknowledged states, hiding until substantive changes, notes, and pinning into the decision queue. Preserve the existing rules for returning findings to attention after new measurements change their substance. Keep calculation history, scheduling, and exclusions accessible through secondary disclosure.

Requirements: REQ-002

## I-5: Validate usability, accessibility, and domain guarantees

Validate the combined flow in the real browser and Electron interfaces, including discrepancy investigation, keyboard and screen-reader access, enlarged text, narrow screens, and action failures. Compare task completion, time, and erroneous actions before and after the changes. Verify the applicable n55–n58 domain guarantees, document observed results separately from expected benefits, and record unresolved acceptance gaps.

Requirements: REQ-001, REQ-002
Decisions: DEC-001
