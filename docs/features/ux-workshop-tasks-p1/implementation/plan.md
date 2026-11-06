---
type: plan
feature: ux-workshop-tasks-p1
title: Task-oriented workshop maintenance, sign-in continuity, and laboratory connection
issues:
  - id: I-1
    title: Organize workshop maintenance around user tasks
    summary: Provide a concise workshop environment overview with separate entry points for backup and restore, tablet connection, external services, laboratories, and resources. Reveal certificate details, addresses, and diagnostics on demand while preserving existing access restrictions, including tablet restrictions. Verify navigation, keyboard access, focus, and readability in narrow and low windows.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Provide an explicitly confirmed workshop restore flow
    summary: Make backup and restore accessible through the maintenance task flow, requiring a separate explicit confirmation before replacing the current workshop. Verify successful restoration, cancellation, and failure in the real interface, including that cancellation does not overwrite the current workshop and that failures provide an understandable recovery path.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Prioritize continuation of the last workshop at startup
    summary: Highlight the last workshop and its Continue action in the desktop launcher, with other folders and detailed logs available separately. Verify first launch, continuation of an existing workshop, and an unavailable last workshop, ensuring that users can reach another folder and inspect startup errors using the keyboard.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Expose sign-in progress and resume pending publication
    summary: Show waiting-for-browser, connected, and incomplete-sign-in states inside the application, with retry and a clear return to the pending publication. Preserve publication context across cancellation and retry, and verify that repeated actions or delayed responses do not silently create duplicate publications. Validate application behavior and accessible status feedback; real macOS and Windows browser-return security acceptance remains owned by desktop-macos-windows/REQ-091, alongside its existing platform scope.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Explain laboratory applicability and terms before connection
    summary: Present equipment and material compatibility, source identity, available measurements, and limitations before laboratory connection is confirmed. Make hashes and full release contents available in details while ensuring material usage conditions, permissions, and authorship remain accessible before consent. Verify file and cloud connection paths, cancellation, absent measurements, and accessible disclosure behavior in the real interface.
    requirements: [REQ-092]
    decisions: []
  - id: I-6
    title: Confirm laboratory source updates and preserve rollback
    summary: Present a comparison before updating a work's laboratory source, including changed and disappearing colors, and require explicit confirmation. A confirmed update must create a new work version and preserve a usable return to the previous source; cancellation must retain the current version and source. Verify confirmation, cancellation, failure, repeated actions, and delayed responses while checking that work settings and measurement history remain intact.
    requirements: [REQ-092]
    decisions: []
updated: 2026-11-06
---

# Implementation plan — [P1] Обслуживание, вход и подключение лаборатории

## I-1: Organize workshop maintenance around user tasks

Provide a concise workshop environment overview with separate entry points for backup and restore, tablet connection, external services, laboratories, and resources. Reveal certificate details, addresses, and diagnostics on demand while preserving existing access restrictions, including tablet restrictions. Verify navigation, keyboard access, focus, and readability in narrow and low windows.

Requirements: REQ-001

## I-2: Provide an explicitly confirmed workshop restore flow

Make backup and restore accessible through the maintenance task flow, requiring a separate explicit confirmation before replacing the current workshop. Verify successful restoration, cancellation, and failure in the real interface, including that cancellation does not overwrite the current workshop and that failures provide an understandable recovery path.

Requirements: REQ-001

## I-3: Prioritize continuation of the last workshop at startup

Highlight the last workshop and its Continue action in the desktop launcher, with other folders and detailed logs available separately. Verify first launch, continuation of an existing workshop, and an unavailable last workshop, ensuring that users can reach another folder and inspect startup errors using the keyboard.

Requirements: REQ-002

## I-4: Expose sign-in progress and resume pending publication

Show waiting-for-browser, connected, and incomplete-sign-in states inside the application, with retry and a clear return to the pending publication. Preserve publication context across cancellation and retry, and verify that repeated actions or delayed responses do not silently create duplicate publications. Validate application behavior and accessible status feedback; real macOS and Windows browser-return security acceptance remains owned by desktop-macos-windows/REQ-091, alongside its existing platform scope.

Requirements: REQ-002

## I-5: Explain laboratory applicability and terms before connection

Present equipment and material compatibility, source identity, available measurements, and limitations before laboratory connection is confirmed. Make hashes and full release contents available in details while ensuring material usage conditions, permissions, and authorship remain accessible before consent. Verify file and cloud connection paths, cancellation, absent measurements, and accessible disclosure behavior in the real interface.

Requirements: REQ-092

## I-6: Confirm laboratory source updates and preserve rollback

Present a comparison before updating a work's laboratory source, including changed and disappearing colors, and require explicit confirmation. A confirmed update must create a new work version and preserve a usable return to the previous source; cancellation must retain the current version and source. Verify confirmation, cancellation, failure, repeated actions, and delayed responses while checking that work settings and measurement history remain intact.

Requirements: REQ-092
