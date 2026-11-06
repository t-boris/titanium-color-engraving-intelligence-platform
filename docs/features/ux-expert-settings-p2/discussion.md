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

### Implementation · 2026-11-06

MarkView browser testing found that the optional study banner inserted literal 'null' in the ordinary theme. Fixed the shell's child list and confirmed on reload that the stray text is absent and compact density remains selected; regression coverage added.

### Implementation · 2026-11-06

Full rerun: pytest -q -rs -n 12, 3005 passed, 0 skipped. During that run a MarkView browser check found and fixed ordinary-theme stray text; the affected router/accessibility tests were rerun afterwards: 52 passed. Wheel rebuilt after that fix. Workshop-lighting/tablet comparison and Electron UI review remain incomplete.

### Implementation · 2026-11-06

Lifecycle discrepancy: MarkView automatically changed this feature to implemented using prior merged commit 3641c79 (technical navigation only). This does not establish that the new branch's grid, density and study variant were merged or released, nor that REQ-001's workshop-lighting/tablet comparison or I-6 integrated review was completed. REQ-001 remains unticked. Do not treat the automatic feature status as proof of those remaining criteria.

### Implementation · 2026-11-06

Electron verification on 2026-11-06: development Electron 33.4.11 with isolated shell profile and seeded disposable workshop /tmp/titanium-expert-electron-fixture displayed version 0.40.0. Selected Compact in Display settings; created a disposable capture setup; opened the 24-patch reference editor; entering L=150 showed its error, retained input and focused the field; correcting to 40 saved the custom reference and Restore published values returned it to published. Opened a seeded laser, expanded Technical data and opened Charts; the group also displayed Pulse waveforms, Test report and Documents. Electron --smoke separately returned smoke=ok, ui=2. This is a desktop scenario, not tablet/workshop-lighting or before/after operator timing evidence.

### Implementation · 2026-11-06

MarkView browser keyboard check on disposable reference editor: starting at Patch 1 L, successive Tab presses focused Patch 1 a, Patch 1 b and Patch 2 L. This confirms the beginning of the declared traversal, not a complete keyboard or screen-reader audit.

### Implementation · 2026-11-06

Additional MarkView browser inspection of the light study preview found dark-on-dark first-screen panels. Updated the study-only colors for one-screen panels, sticky list toolbar and dashboard cards; screenshot review showed readable headings and text. Also checked the empty color-map and laser charts screens. This does not establish contrast across all screens, actual workshop conditions or tablet usability.

### Implementation · 2026-11-06

Additional MarkView browser check on disposable capture setup: simulated 200% page enlargement with CSS zoom in a 1052×907 window, both compact and normal density. L=150 retained the entered value, remained focused and displayed its validation message; the reference input measured about 198–209×90 CSS screen pixels and the document width (1035) stayed within the viewport (1052). Visually inspected the compact error. This is a desktop CSS-zoom simulation for one form, not browser text-only zoom, a low-window audit, screen-reader testing or a physical tablet.
