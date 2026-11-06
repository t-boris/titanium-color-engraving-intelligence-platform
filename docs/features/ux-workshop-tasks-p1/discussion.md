# Discussion — [P1] Обслуживание, вход и подключение лаборатории

### Codex · 2026-11-06

The user clarified that the entire application and its code must be in English. This applies to implementation and verification across all seven P1 features. Work remains in progress; existing Russian UI and code are being migrated.

### Codex · 2026-11-06

Implementation progress: file and cloud releases now show equipment, material, usage permissions, attribution, schema limitations, and the full hash before an explicit connection. Cloud review stages the downloaded file without connecting; confirmation checks its hash again, while cancel discards it. The cloud sign-in state now handles cancellation and stale responses, and an unfinished publication remains visible while signed out and resumes through the existing retry operation. Focused UI and API tests pass. Further translation and real desktop acceptance remain outstanding; the feature remains implementing.

### Agent · 2026-11-06

Shared background task progress, cancellation effects, recovery and screen-reader announcements now use English. Upload, recheck and release-connection tests passed, including stop behavior and retained results. Other application screens remain to be translated; feature remains implementing.

### Agent · 2026-11-06

Draft PR for all seven P1 features: https://github.com/t-boris/titanium-color-engraving-intelligence-platform/pull/33. Implementation and acceptance remain in progress; the PR is not yet ready to merge.

### Agent · 2026-11-06

The equipment-reference translation exposed legacy sentinel and handwritten-note formats. Current and legacy forms now both remain unresolved until confirmed; regression tests cover both, and the controller renders the old marker and units in English without rewriting stored data. Laser-limit, passport and open-question tests: 68 passed.

### Agent · 2026-11-06

Full automated regression on commit 1b990be: 2,997 tests passed (one existing Python escape-sequence warning); desktop shell tests: 36 passed. The PR remains a draft and the feature remains implementing because the applicable real-operator and accessibility acceptance has not yet been completed.

### Agent · 2026-11-06

Implementation was pushed directly to main at 0121169 at the user's request. Local regression tests passed; the user requested no further operator or screen-reader testing for now. The feature has not been marked verified.
