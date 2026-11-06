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

### Implementation · 2026-11-06

Touch-target follow-up: list chips, filter selects and row action buttons now have a 44px minimum height under pointer:coarse in both normal and compact modes. In the MarkView desktop browser, simulated activation of that media rule using its CSSOM contents and measured 44px for representative Works list controls in both modes. This is not a physical tablet or full touch-usability assessment.

### Implementation · 2026-11-06

The same simulated coarse-pointer check also measured width: representative visible Works chips, selects and row-action buttons had minimum rendered width and height of 44px in both density modes. Actual touch interaction on a physical tablet is still unverified.

### Implementation · 2026-11-06

Keyboard follow-up: in the MarkView browser on the disposable setup, 71 successive Tab presses moved from Patch 1 L to Patch 24 b; intermediate focus was sampled at Patch 1 a/b, Patch 2 L, Patch 12 b and Patch 23 b/Patch 24 L/a/b. The browser tool's Shift+Tab command left focus unchanged even on an ordinary summary control, so it was not used as evidence of an application defect. In development Electron 0.40.0 on a separate disposable workshop, actual Shift+Tab moved Patch 1 a to Patch 1 L and Patch 2 L to Patch 1 b; Tab moved back to Patch 1 a. This is not a complete screen-reader audit.

### Implementation · 2026-11-06

Responsive MarkView browser check using same-origin iframe viewports on a disposable workshop: Works at 320×600 and 800×600 in both normal and compact modes showed 20 rows and document scrollWidth equaled clientWidth (303 and 783 respectively). At 320×600 in both modes, a capture reference L=150 stayed focused and retained the error message; input rendered about 66–68×45px and document scrollWidth equaled clientWidth (303). Visually inspected the compact reference error. This checks those screens in a desktop browser, not a physical tablet, touch ergonomics, all screens or real workshop lighting.

### Implementation · 2026-11-06

Additional low-window check in same-origin desktop browser frames at 800×400: Works loaded 20 rows in both densities, document width stayed 783px (client width 783px), and the last row action could be scrolled into view and focused (its bounds were y=236–264 in the 400px viewport). Scrolling was invoked explicitly; automatic keyboard scrolling and actual tablet use were not established.

### Implementation · 2026-11-06

Further inspection of the light-study variant in MarkView found low-contrast definition values on the Workshop screen (light text on white); corrected them to use the theme text color and checked computed colors. The Network screen was also inspected on the disposable server. Other screens and the physical workshop/tablet evaluation remain unverified.

### Implementation · 2026-11-06

Long-name stress check in MarkView desktop browser at a 320px iframe viewport: replaced the visible first Works row name and equipment label in the disposable DOM with unbroken strings of 150 and 250 characters. In both normal and compact density, each wrapped (scrollWidth equaled clientWidth), and document scrollWidth remained 303px equal to clientWidth. This covers only the tested Works row, not all names, dropdowns, text enlargement or tablet interaction.

### Implementation · 2026-11-06

Inspected the light-study Research workflow in MarkView with a disposable workshop. The stock chooser dialog initially had dark text over a dark modal surface. Updated study-only modal colors and checked the actual chooser again: title, explanation, close button and list were readable in the desktop screenshot. This does not certify every dialog or satisfy the actual workshop-lighting/tablet comparison.

### Implementation · 2026-11-06

While checking the light-study stock chooser with actual Tab in MarkView, focus left the dialog after its sort selector. The browser/OS skipped buttons even though the old trap assumed native Tab would visit every focusable element. The shared dialog now explicitly traverses rendered, enabled controls and skips hidden or inert ones. After the fix, Tab moved from sort to the first Choose button; 30 further Tab presses stayed in the dialog, and Escape returned focus to the opener. Existing dialog regressions and a new skipped-control case are run separately.

### Implementation · 2026-11-06

Verified the updated dialog traversal in development Electron 0.40.0 on a disposable workshop: Tab moved from Sort order to the first Choose button, Shift+Tab returned to Sort order, and Escape closed the chooser and returned focus to Material and stock: choose. This supplements the MarkView 30-Tab check; it does not establish a full screen-reader or tablet audit.

### Implementation · 2026-11-06

After the shared dialog focus change, pytest -q -rs -n 12 completed with 3005 passed, 0 skipped; the additional test for skipping a non-rendered control was added after collection began and passed in the targeted dialog run (4 passed). Desktop Node tests passed 36/36 and the 0.40.0 wheel built. No release or CI result is implied.

### Implementation · 2026-11-06

The prior coarse-pointer sizing applied under main, but dialogs are body-level siblings: the stock chooser close button measured 34×34px in the simulated coarse-pointer check. Added 44px minimum sizing for dialog buttons and selects in both densities. MarkView desktop simulation using the actual coarse-pointer CSSOM rules measured close at 44×44, both selects at 44px height and representative Choose buttons at least 44px high. This is not a physical tablet usability assessment.

### Implementation · 2026-11-06

MarkView browser first-run light-study scenario on a new disposable 0.40.0 workshop: vector and photo-engraving empty states opened. Created synthetic laser/lens/stock only in that workshop, selected a synthetic 64×64 PNG in New work, reviewed the four generated previews, chose Color regions and reached settings. With no measurements the UI explained the missing measurements and disabled Create work. Back returned to the result step with Color regions still selected and all four images loaded. No work or measurement was created and no operator timing, physical engraving, export or tablet test is claimed.

### Implementation · 2026-11-06

After the operator removed delivery blocks, opened PR #35 and enabled the previously disabled CI workflow for the requested checks. Additional domain regression selection passed 16 tests covering stored picture through scale/width/undo, palettes, exported-file and measurement history, delayed preview responses and preview/export smoothness. Physical workshop-lighting/tablet comparison remains pending and the light theme remains research-only.

### Codex · 2026-11-06

Post-release CI run 42237134177: Linux Python 3.11 and 3.12 failed five tests each, despite the earlier local suite passing. Two nested pytest.approx assertions are incompatible with pytest 9.2, and one AI form test depends on local credentials; fixes reproduced locally with pytest 9.2. Two contour round-trip checks are under investigation in a matching Linux environment. Internal beta 0.40.0 remains released; do not treat CI as passed.

### Codex · 2026-11-06

The two Linux contour failures were reproduced in an amd64 Linux container. The 0.40.0 preview and LightBurn parser used different curve flattening resolutions, giving roughly 1.5–1.8% area difference on small regions. Increasing both sampling precisions made the existing 1% checks pass without relaxing them; broader geometry and cache regressions are running for patch 0.40.1.

### Codex · 2026-11-06

Patch validation: the Linux amd64 container passed 78 contour, LightBurn and grayscale tests with the original contour area tolerance; the three pytest 9.2 and AI-credential-dependent cases also passed locally. The drawing cache version is advanced for the more accurate contours. Full pytest and the 0.40.1 desktop build are in progress.

### Codex · 2026-11-06

Internal beta 0.40.1 was merged as PR #36, published and installed after a verified full workshop backup. The operator's MarkView tab and /api/version both report 0.40.1. The old CI run also showed a macOS LAN TLS read timeout; the same test passed repeatedly on the local Mac, so its cause is not yet established. The new full suite and CI continue; the physical tablet/workshop-light comparison remains deferred, and REQ-001 must not be marked accepted on simulated tests alone.
