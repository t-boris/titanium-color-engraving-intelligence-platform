---
type: plan
feature: ux-experiment-planning-ai-p1
title: Goal-driven experiment planning and contextual AI assistance
issues:
  - id: I-1
    title: Define planning context and test proposal contracts
    summary: Define the shared context and proposal contracts for goal-driven planning and AI assistance, covering the current work or experiment, material, equipment constraints, available results, source references, and missing data. Specify how proposals retain their originating context and how stale context is detected before creation. Record unresolved data-model choices as open assumptions; this decomposition remains a draft proposal.
    requirements: [REQ-001, REQ-002]
    decisions: []
  - id: I-2
    title: Present one explained next test for the selected goal
    summary: Provide one planning entry with color, text, line, and image goals. Use the current context to present one recommended next test, explaining what it will establish, its physical size, and estimated duration before creation. When evidence or estimation inputs are insufficient, show the specific reason without presenting unsupported precision.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Integrate advanced manual planning with laser constraints
    summary: Expose manual plate types and full axis sweeps through an advanced mode within the same planning flow. Preserve applicable context and settings when switching modes, explain incompatible settings, and enforce existing laser constraints during configuration and creation. Keep manual planning usable when AI is unavailable.
    requirements: [REQ-001]
    decisions: []
  - id: I-4
    title: Add contextual AI explanations and test suggestions
    summary: Add Explain result and Suggest test actions alongside the current work or experiment. Show which contextual data and sources support each response, identify missing evidence, and ensure these advisory actions do not create or modify domain artifacts. Handle absent credentials, network failures, and delayed responses without blocking ordinary work or replacing newer context.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Create a proposed test through an explicit artifact action
    summary: Connect recommended and AI-proposed tests to an explicit Create test action that displays the proposal being committed and validates current context and laser constraints. Return a link to the created plate, preserve the proposal on failure, and prevent duplicate plates from repeated clicks or retries. Verify that conversational requests alone cannot bypass the separate creation action.
    requirements: [REQ-001, REQ-002]
    decisions: []
  - id: I-6
    title: Link research history to its originating objects
    summary: Make research history accessible from its related work or experiment and preserve existing session links. Persist the associations needed to recover the relevant conversation, evidence references, proposals, and created plates across navigation and reloads. Define behavior for unavailable related objects and preserve existing credential protections.
    requirements: [REQ-002]
    decisions: []
  - id: I-7
    title: Verify workflow accessibility, failures, and domain regressions
    summary: Validate the combined workflow in the real browser and Electron interfaces across all four goals, advanced planning, contextual advice, explicit creation, and history recovery. Cover missing measurements, absent credentials, offline operation, delayed responses, creation failures, repeated clicks, back navigation, keyboard and screen-reader access, text enlargement, and narrow or low windows. Check applicable n58 domain guarantees and compare task success, repeated context entry, returns, and errors against a baseline; keep numerical improvement targets open until measured.
    requirements: [REQ-001, REQ-002]
    decisions: []
updated: 2026-11-06
---

# Implementation plan — [P1] Тест от цели и AI в контексте

## I-1: Define planning context and test proposal contracts

Define the shared context and proposal contracts for goal-driven planning and AI assistance, covering the current work or experiment, material, equipment constraints, available results, source references, and missing data. Specify how proposals retain their originating context and how stale context is detected before creation. Record unresolved data-model choices as open assumptions; this decomposition remains a draft proposal.

Requirements: REQ-001, REQ-002

## I-2: Present one explained next test for the selected goal

Provide one planning entry with color, text, line, and image goals. Use the current context to present one recommended next test, explaining what it will establish, its physical size, and estimated duration before creation. When evidence or estimation inputs are insufficient, show the specific reason without presenting unsupported precision.

Requirements: REQ-001

## I-3: Integrate advanced manual planning with laser constraints

Expose manual plate types and full axis sweeps through an advanced mode within the same planning flow. Preserve applicable context and settings when switching modes, explain incompatible settings, and enforce existing laser constraints during configuration and creation. Keep manual planning usable when AI is unavailable.

Requirements: REQ-001

## I-4: Add contextual AI explanations and test suggestions

Add Explain result and Suggest test actions alongside the current work or experiment. Show which contextual data and sources support each response, identify missing evidence, and ensure these advisory actions do not create or modify domain artifacts. Handle absent credentials, network failures, and delayed responses without blocking ordinary work or replacing newer context.

Requirements: REQ-002

## I-5: Create a proposed test through an explicit artifact action

Connect recommended and AI-proposed tests to an explicit Create test action that displays the proposal being committed and validates current context and laser constraints. Return a link to the created plate, preserve the proposal on failure, and prevent duplicate plates from repeated clicks or retries. Verify that conversational requests alone cannot bypass the separate creation action.

Requirements: REQ-001, REQ-002

## I-6: Link research history to its originating objects

Make research history accessible from its related work or experiment and preserve existing session links. Persist the associations needed to recover the relevant conversation, evidence references, proposals, and created plates across navigation and reloads. Define behavior for unavailable related objects and preserve existing credential protections.

Requirements: REQ-002

## I-7: Verify workflow accessibility, failures, and domain regressions

Validate the combined workflow in the real browser and Electron interfaces across all four goals, advanced planning, contextual advice, explicit creation, and history recovery. Cover missing measurements, absent credentials, offline operation, delayed responses, creation failures, repeated clicks, back navigation, keyboard and screen-reader access, text enlargement, and narrow or low windows. Check applicable n58 domain guarantees and compare task success, repeated context entry, returns, and errors against a baseline; keep numerical improvement targets open until measured.

Requirements: REQ-001, REQ-002
