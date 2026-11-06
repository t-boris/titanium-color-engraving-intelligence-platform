# Discussion — [P1] Короткие формы фотогравировки и надписей

### Answer to Q-001 · 2026-11-06

REQ-001 требует сравнения с прежним состоянием. Какое состояние должно служить точкой сравнения?

A. Сравнивать с состоянием перед последним изменением параметров.

### Codex · 2026-11-06

The user clarified that the entire application and its code must be in English. This applies to implementation and verification across all seven P1 features. Work remains in progress; existing Russian UI and code are being migrated.

### Codex · 2026-11-06

Implementation progress: photo-work and vector photo-zone panels now compare against the preview immediately before the latest successful change. Preview URLs resolve to their cached version; a long pointer or held-key slider gesture is saved as one change. Focused API and UI tests pass; browser and Electron acceptance and the remaining English translation are still outstanding. The feature remains implementing.

### Agent · 2026-11-06

English-language work is in progress across shared photo mode descriptions, work composition and engraving task review. Mode keys and saved work remain compatible. Targeted photo engraving, composition and review tests passed. Additional application screens still require translation; feature remains implementing.

### Agent · 2026-11-06

The vector photo-zone panel now uses English for engraving kinds, scale selection, power, color-map actions and guidance. Existing edit, undo and selection behavior remains in place. Editor/workspace/plan checks passed after updating affected expectations. Translation of other application screens remains in progress.

### Codex · 2026-11-06

The user requires English throughout the application and English-only code; Russian is reserved for conversation. Translation is in progress across shared screens and server messages. Existing user data and legacy compatibility are preserved. This feature remains implementing until the remaining work and verification are complete.

### Agent · 2026-11-06

English-only UI progress: the shared photo panels, inscription editor, font picker and keyboard controls have been translated. Photo/vector panel tests and 44 accessibility scenarios passed. Other application screens still contain Russian; the feature remains implementing.

### Agent · 2026-11-06

Vector work creation, recipe selection, export, and measured-versus-estimated preview disclosures now use English. Relevant form, workspace, editor, and laboratory-source tests passed after updating the translated labels. The remaining editor screens and end-to-end acceptance are still in progress.

### Agent · 2026-11-06

Draft PR for all seven P1 features: https://github.com/t-boris/titanium-color-engraving-intelligence-platform/pull/33. Implementation and acceptance remain in progress; the PR is not yet ready to merge.

### Agent · 2026-11-06

English-language fixture regression batch passed: 628 tests across the affected screens, including photo, lettering, vector, evidence and lifecycle flows. This is automated evidence; real operator and accessibility acceptance remain pending.

### Agent · 2026-11-06

All three coloring prompts now request English notes. Live OpenAI calls on synthetic vector, photo-parts and photo-objects contexts returned English notes, with no images or workshop data sent. A related regression run passed 117 tests.

### Agent · 2026-11-06

Full automated regression on commit 1b990be: 2,997 tests passed (one existing Python escape-sequence warning); desktop shell tests: 36 passed. The PR remains a draft and the feature remains implementing because the applicable real-operator and accessibility acceptance has not yet been completed.

### Agent · 2026-11-06

A real Chrome round trip on an isolated synthetic work with a measured synthetic gray ramp confirmed: creating a photo zone, setting brightness in the inspector, opening its detailed editor, changing contrast, comparing the previous prediction, undoing there, returning to the work, and undoing the inspector change. The check exposed a misleading claim that the scale was measured at the zone width; the inspector and zone card now disclose the actual measurement widths or uncertainty, with targeted regression tests. Electron screen-reader and operator acceptance remain pending.

### Agent · 2026-11-06

The measurement-width disclosure fix is in PR #33 at commit 51d7ecb. The affected vector editor, detailed photo-zone, dot-width and language-guard suite passed 55 tests after the fix. The earlier full 2,997-test run was on 1b990be, before this two-file change.

### Agent · 2026-11-06

Commit 1d8f277 keeps the previous visual comparison when a nonvisual setting, such as AI photo permission, leaves the preview unchanged. Affected photo work, preview, vector-zone and English-code checks passed: 54 tests. The full 2,997-test run remains evidence for 1b990be; subsequent changes have targeted verification.

### Agent · 2026-11-06

Implementation was pushed directly to main at 0121169 at the user's request. Local regression tests passed; the user requested no further operator or screen-reader testing for now. The feature has not been marked verified.
