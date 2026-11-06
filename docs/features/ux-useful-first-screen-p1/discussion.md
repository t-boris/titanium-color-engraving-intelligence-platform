# Discussion — [P1] Первый полезный экран без ожидания скрытых вкладок

### Codex · 2026-11-06

The user clarified that the entire application and its code must be in English. This applies to implementation and verification across all seven P1 features. Work remains in progress; existing Russian UI and code are being migrated.

### Codex · 2026-11-06

Implementation progress: the local experiment catalog now renders while the laser list is still loading, remains usable when the laser request fails, and offers a separate retry. Existing list state stays intact when laser data arrives; an invalid laser filter falls back to the full list. Automated delayed-request and failure tests are in progress. Real cold and warm before/after timing and browser/Electron acceptance are not yet recorded; the feature remains implementing.

### Codex · 2026-11-06

Additional progress: photo works and vector photo zones now render their available predictions before measured scales load. Scale loading has a local error and retry, and stale responses for a previous work width are ignored. Delayed and failed scale requests are covered by focused tests. Real browser/Electron acceptance and cold/warm timing remain outstanding; status remains implementing.

### Codex · 2026-11-06

Verification update: 127 related automated tests passed across the experiment catalog, photo work, photo zone, scale context, guide and material picker. The chosen scale is opened after delayed loading, and updated server ordering is retained after resize. The actual browser/Electron checks and cold/warm before-and-after measurements remain open; the feature is still implementing.

### Agent · 2026-11-06

The shared work catalog now uses English for work types, filters, states, creation and actions. Rename, copy, deletion safeguards, pagination and return-to-position behavior were checked. Translation remains incomplete elsewhere; feature remains implementing.

### Agent · 2026-11-06

Prepared two isolated copies of the same synthetic workshop and the original merge-base build for a browser timing comparison. Full regression run is in progress; timing and real-user acceptance are not yet complete.

### Agent · 2026-11-06

Browser timing comparison on this Mac, headless Chrome, one identical synthetic vector work in isolated workshop copies; five alternating baseline/current trials. Time from navigation to the work card appearing: baseline median cold browser cache 164.3 ms, warm 107.3 ms; current 161.8 ms and 113.3 ms. Cold means browser cache cleared, not a cold server or operating-system cache; both servers were already running. This small local sample does not establish a speed improvement or satisfy representative desktop/operator acceptance.

### Agent · 2026-11-06

Draft PR for all seven P1 features: https://github.com/t-boris/titanium-color-engraving-intelligence-platform/pull/33. Implementation and acceptance remain in progress; the PR is not yet ready to merge.

### Agent · 2026-11-06

Full automated regression on commit 1b990be: 2,997 tests passed (one existing Python escape-sequence warning); desktop shell tests: 36 passed. The PR remains a draft and the feature remains implementing because the applicable real-operator and accessibility acceptance has not yet been completed.

### Agent · 2026-11-06

Commit 1d8f277 keeps the previous visual comparison when a nonvisual setting, such as AI photo permission, leaves the preview unchanged. Affected photo work, preview, vector-zone and English-code checks passed: 54 tests. The full 2,997-test run remains evidence for 1b990be; subsequent changes have targeted verification.

### Agent · 2026-11-06

Implementation was pushed directly to main at 0121169 at the user's request. Local regression tests passed; the user requested no further operator or screen-reader testing for now. The feature has not been marked verified.
