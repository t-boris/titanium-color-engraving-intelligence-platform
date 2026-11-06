# Discussion — [P2] Плотность, технические справки и калибровка

### Answer to Q-001 · 2026-11-06

Нужен ли выпускаемый светлый вариант темы после проверки на рабочем освещении и планшете?

A. Сначала сравнить читаемость и действия на реальных условиях, затем решить о выпуске светлой темы.

### Implementation · 2026-11-06

Work in progress: REQ-003 technical data grouping already exists in 3641c79, with route coverage in tests/test_device_navigation_ui.py. REQ-002 grid and REQ-001 density controls are being implemented on feature/ux-expert-settings; criteria remain unticked pending verification. DEC-001 comparison under workshop lighting and on a tablet remains outstanding.

### Implementation · 2026-11-06

REQ-002 implemented: 24 Lab patches in row-major order, per-field validation, JSON exchange, source and white point, and published reset. Tests cover invalid input, payload round-trip and accepted observations surviving reference changes. REQ-003 was already implemented and its routes are covered. Density setting and persistence are implemented, but REQ-001 remains open: full real-interface and tablet checks, an experimental light variant and the DEC-001 workshop comparison have not been performed. Chrome access host was unavailable. No results for lighting, tablet, Electron or before/after performance are claimed.

### Implementation · 2026-11-06

Follow-up: although browser-tab integration was unavailable, a separate native Chrome tab opened the disposable workshop at /#/setup?tab=display. The accessibility tree showed the Display settings and Normal selector. Interaction could not be completed because the user changed the Chrome window; this does not establish the compact-mode, lighting, tablet, or Electron criteria.

### Implementation · 2026-11-06

In MarkView's browser on disposable seeded workshop, verified compact density is applied and persisted across navigation. Opened the capture reference editor: 24 patches / 72 individually named controls; entering L=150 and saving retained 150, marked the control invalid, displayed its permitted range, and focused it. Screenshot inspected at desktop size. This is not a tablet, Electron, lighting, complete keyboard or theme-comparison result.

### Implementation · 2026-11-06

Prepared an explicitly labeled light study preview behind ?theme-study=light, with no stored theme preference or release decision. In MarkView on a disposable workshop, inspected Capture settings and Works in both the normal theme and study variant; repaired field contrast seen in the preview. This limited desktop inspection is not the DEC-001 comparison under workshop lighting and on a tablet, and does not validate every specialized screen.

### Implementation · 2026-11-06

Validation so far: full pytest run reported 3003 passed and one outdated Settings tab expectation; updated that test and all 103 affected tests passed on rerun. Desktop Node suite passed 36/36; the 0.40.0 wheel built and a disposable-workshop smoke returned 0.40.0. CI workflow is disabled and the goal excludes a PR; no CI run or published release is claimed. Actual workshop lighting, tablet, Electron UI and before/after performance evaluation remain outstanding.
