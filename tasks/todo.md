# Photo engraving: measured quality, best settings per mode, experiments that converge (goal set 2026-10-24)

Operator's goal (2026-10-24): every kind of engraving gets the attention colour gets; photo engraving (dot modes such as Atkinson, Jarvis,
and grayscale) is analysed after every photograph: what makes it darker, lighter, sharper, softer, which mode for which case; when a
mode is chosen for a photo zone or work, the best known settings are filled in; when knowledge is missing the laboratory proposes the
experiment (e.g. one plate, 8 copies of one picture at different settings); every photograph improves the defaults. Mid-goal requests
(same day): "create one next compact LightBurn test for this goal; first check for a pending plate" and "OPENAI_API_KEY не найден … Почини".
Feature: `docs/features/photo-engraving-quality` (MarkView).

## What the data says before any change (live workshop, read only)
- No plate waits for a photograph: grey-scale plates 25 and 38 are photographed and accepted; plans 35/37 are draft photo works.
- Dot-mode engravings photographed so far (tonal profile of the check, L* range white→black, rank correlation):
  Jarvis 25 % 125 mm/s 60 kHz 200 ns 0.01 mm (pair 118) range 48.4, rho 0.94 — the operator set these by hand in LightBurn; the
  app had proposed 12.4 % at 0.0169 mm from the colour scale. Jarvis 30 % 150 mm/s 0.0231 mm dot corr. 0.02 (pair 106) range 27.9,
  rho 0.89. Jarvis 12.5 % 0.0169 (114) range 13.9 weak; Atkinson 15 % 0.0254 (112) 12.0, rho −0.1; Atkinson 10.2 % 0.0169 (116) 2.6;
  Halftone 12.1 % (116) 2.7: the pictures nearly vanished.
- The operator's own archive (Dropbox/Sirius Art, 9 Jarvis layers): 25 %, 125–150 mm/s, 60 kHz, 0.01 mm (2540 dpi), dot
  correction 0.01 mm in some.
- Detail prototype (band-pass regression of the photograph on the picture, real pairs): grayscale works keep 0.85–1.0 of the
  picture's contrast at 0.4 mm and 0.3–0.85 at 0.2 mm; zone layers need the zone's own region geometry (prototype read 0).
- The AI key: under the desktop shell `research._api_key` reads only the environment; an app opened from Finder has none.

## Steps
- [x] 1 AI key kept by the workshop (`<data>/ai/openai.key`, 0600), entered on «Сеть»; environment still first; never in backups,
      diagnostics or lab releases (BUG-007)
- [x] 2 Plate `photo_variations`: one picture × 2–8 settings (mode, power, speed, frequency, pulse width, interval, dot width), each
      copy = picture layer + grey ramp layer with the same settings, markers and QR; made from a photo zone, a photo work or an
      uploaded picture; default variants centred on the best known settings of the mode
      Done: 2–12 copies (8 by default), labels, the picture stored once (`plan["pictures"]`), a window of the file's picture at its real
      size (`variation_window`), «Подобрать настройки: 8 копий» on photo works and zones, the plate dialog with an uploaded picture,
      default copies by `photo_quality.variants_around` (DEC-003); the tone measures of `photo_quality.tone` (DEC-001) are in, the detail
      measure is written but not yet run on photographs (step 4). Tests: `tests/test_photo_variations.py` (19), UI tests extended.
- [ ] 3 Release 0.32.0 (key + plate), desktop build, deploy; the first plate made in the workshop and handed over with screen steps
- [ ] 4 `photo_quality.py`: tone (distinguishable levels, darkness, contrast, shadows/highlights kept, dot gain), detail at
      0.2/0.4/0.8 mm, grain, scan-direction blur — from the check (new photographs) and backfilled for accepted ones
- [ ] 5 Conclusions after every photograph for every photo layer, with the setting to change for darker/lighter/sharper/softer;
      the plate's copies ranked; the experiment page and «Выводы» show them; the image purpose stops saying only "needs a test"
- [ ] 6 Knowledge per laser, lens, titanium and mode: best measured settings, measured sensitivities (same picture, one setting
      changed), priors marked as such
- [ ] 7 Photo zones and photo works fill in the best settings when a mode is chosen; «Темнее / Светлее / Чётче / Мягче» apply the
      next measured step; what the values rest on is shown
- [ ] 8 Proposals: a mode without measured best settings, or a best at the edge of what was tried, proposes the next variations
      plate (centred on the best, steps halved when the best stays in the middle)
- [ ] 9 Release 0.33.0, deploy, read-only check on the live data

# Electron: desktop workshop and laboratory exchange (goal set 2026-10-24)

Specification `docs/features/electron` read in full (REQ-080..087, DEC-021..041, Q-001..009, F-001, implementation/plan.md) with
the main feature's REQ-043/DEC-020. Commits go straight to `main` and CI is off (project CLAUDE.md, operator 2026-10-19): the
goal's branch / pull request / CI / merge steps are replaced by commits to `main` and the local suite (`-n 12`, none skipped).
Answers given on 2026-10-24 are recorded as accepted decisions DEC-042..DEC-048 (electron) and DEC-121 (main feature).
Plan: `/Users/boris/.claude/plans/distributed-frolicking-koala.md`.

## Stage A — local laboratory exchange (REQ-083/084/085), 0.29.0
- [x] A1 Golden local snapshot of colormap / palette / curves / scales before the refactor (`tests/labworld.py`, `test_evidence_golden.py`)
- [x] A2 `lab_format.py` + `schemas/tcelab-1.schema.json`: JCS, strict decoder, line framing, incremental hash, limits, safety
- [x] A3 Tables `portable_id`, `pair_row_length`, `lab_export`, `lab_source`, `lab_release`, `lab_withdrawal`
- [x] A4 A connected release is a snapshot store with the main schema (`lab_snapshot.py`): colormap, palette and prediction_store run on it
  unchanged; row lengths from `pair_row_length` where the LightBurn file is not kept (changed from the gather/transform split: smaller change,
  parity by construction)
- [x] A5 DEC-045: tonal curves by engraving (count and Lab), `prediction.ALGORITHM` 2, changed numbers recorded in the golden record
- [x] A6 `lab_export.py`: selection, closure, privacy preview, terms (DEC-042), streaming writer
- [x] A7 `lab_import.py`: staging, validation, progress, cancel, atomic activation, no-op / conflict, disconnect, withdrawals
  (`api/routes_labs.py`, `tests/test_lab_import.py`, `tests/test_lab_api.py`)
- [x] A8 Pinned sources in vector and photo works; update with preview and route back; frozen result on algorithm mismatch
  (`evidence_source.py`; the colour map of a pinned work's dots is its source's; the cleaning and the limits are the own laser's;
  a pinned photo work keeps its exported file as its confirmed result; `tests/test_lab_sources.py`)
- [x] A9 `lab_transfer.py`: transfer experiment from a foreign recipe (a one-cell plate with the complete recipe on the own laser,
  `plans.create_plates` takes a cell recipe and plan data; `tests/test_lab_transfer.py` photographs it and compares by ΔE)
- [x] A10 UI: Моя лаборатория, Подключённые лаборатории, Карточка, source picker, Проверить у себя; ru/en
  (`screens/labs.js`, `screens/lab-source.js`, NAV «Лаборатории»; `tests/test_ui_labs.py`)
- [x] A11 Tests: fixtures, negative fixtures, privacy markers, parity 1e-6, counting, constant memory; benchmark on M2 Ultra
  (`tests/test_lab_memory.py`; `tools/bench_tcelab.py` → `docs/features/electron/benchmarks/`: 10k measurements connect in 2.1 s,
  progress every 0.06 s; 50k in 12 s; reading and snapshot building flat in memory, export ≈1.8 KB per measurement; max_bytes 64 MiB)
- [x] A12 Release 0.29.0: suite 2106 passed none skipped (-n 12, 2:56), version, README, commit, push, tag v0.29.0, backup, deploy, read-only check

## Stage B — safety and desktop (REQ-080/081/082), 0.30.0
- [x] B1 Schema version stamp, migration registry, pre-migration backup, newer-schema refusal, workshop lock (07e8a42; DEC-056; tests/test_migrations.py)
- [x] B2 Full backup / restore (DB + files + labs + manifest); path resolver for another folder (07e8a42; tests/test_backup.py; the workshop screen follows)
- [x] B3 Host / Origin checks; desktop session secret and cookie; upload limits (60c3dbc; DEC-057; tests/test_api_security.py)
- [x] B4 Core for packaging: cli ready line, watchdog, Windows fonts, certifi (60c3dbc); network settings (e939b3f, outbound.py) and diagnostics export (417698f, diagnostics.py)
- [x] B5 `desktop/` Electron Forge shell: launcher screen, sidecar lifecycle, isolation, update check from GitHub Releases (60c3dbc; 16 node tests; applying an update waits for signed builds)
- [ ] B6 PyInstaller onedir sidecar and `--smoke` (60c3dbc); signed macOS build verified on 60c3dbc (Developer ID 3M68DG8S7N, hardened runtime, codesign --verify --deep --strict valid, spctl «Unnotarized Developer ID», packaged app --smoke ok, zip 254 MB); final build after the LAN merge pending
- [x] B7 LAN (DEC-047, DEC-059): workshop CA, TLS server, pairing, devices, revoke (e939b3f; tests/test_lan.py); firewall and pairing on a real Windows machine remain the owner's (REQ-082 c6)
- [x] B8 Manual `desktop.yml` Windows x64 build + smoke passed (run 40118337329; core smoke ok on the runner; installer unsigned, sha256 b9181e19…); GitHub pre-release v0.30.0 (internal beta) carries the macOS zip, the Windows installer and SHA256SUMS.txt; docs/features/electron/builds/
- [x] B9 Release 0.30.0: suite 2149 passed none skipped (-n 12, 3:18), commits 8427528 + 5fa8068, tag v0.30.0, backup titanium-before-0.30.0-20261024T171253Z.sqlite (integrity ok), deployed on 8765 (/api/version 0.30.0, schema stamp 1, workshop.lock held, LAN CA made and LAN off, Host check 421)

## Stage C — cloud (REQ-086/087), 0.31.0
- [x] C1 Neon project `titanium-labs` + Neon Auth (Better Auth, Google shared provider, trusted domain https://titanium-labs-api.vercel.app); schema 0001 applied, RLS, `app_api` role (DEC-043, DEC-058); ids and secrets in ~/.titanium-cloud.env
- [x] C2 Vercel Python API (ed37a05, `cloud/`): catalogue, publications (reserve, 1 MiB chunks, finalize), withdraw, invitations, members, idempotency; deployed at https://titanium-labs-api.vercel.app (env DATABASE_URL app_api, NEON_AUTH_JWKS_URL, NEON_AUTH_ISSUER/AUDIENCE = the Neon Auth host, CLOUD_REPOSITORY=postgres); cloud/tests_live 14 passed on Neon
- [x] C3 Desktop sign-in through the system browser and loopback callback (71c8c7a: `cloud_session.py`, `api/routes_cloud.py`; DEC-060: the handoff of DEC-058 could not work against the real Neon Auth, which authenticates only its HttpOnly signed cookie, so the sign-in is Neon Auth's OAuth provider with PKCE, the cloud's `/signin`, `/consent`, `/auth/return`, a refresh token in `cloud/session.json`; verified end to end against production through the real core, docs/features/electron/cloud-signin-2026-10-24.md; migration 0003 applied; Vercel env ISSUER/AUDIENCE lists, CLOUD_OAUTH_CLIENT_ID, CLOUD_RESOURCE, PUBLIC_BASE_URL)
- [x] C4 In-app catalogue, private labs, publish, connect, update checks (71c8c7a: `cloud_client.py`, `ui/screens/labs-cloud.js`; catalogue, card with terms, connect through the importer, publish = reserve → write → chunks → finalize with retry by key, invitations, members, withdraw, update checks of connected labs)
- [x] C5 Cloud smoke against production passed (docs/features/electron/cloud-smoke-2026-10-24-production.md): publish → anonymous manifest and chunks → connect into a second workshop with the author's store closed → palette equal → withdraw listed; the smoke lab «Smoke laboratory» (c9197ac4…) stays in the public catalogue until the owner decides (no delete endpoint by design)
- [x] C6 Release 0.31.0: suite 2190 passed none skipped (-n 12, 3:22), commits fb95667 + d82be51, tag v0.31.0, backup titanium-before-0.31.0-20261024T190005Z.sqlite (47 MB, integrity ok, 34 tables), deployed on 8765 (/api/version 0.31.0, /api/cloud/account and the catalogue answer from production, Host check 421); DEC-058 as built, DEC-060 proposed, REQ-086 criteria 5 (Windows browser check), 6 (account recovery: Neon Auth's own e-mail flow, not offered on the cloud's page yet) and 13 (terms on cards: shown, to be confirmed by the operator) stay open; desktop builds of 0.31.0: macOS arm64 signed (sha256 b9412d2a…, smoke ok; rebuilt once after the venv's stale metadata made the core say 0.3.1) and Windows x64 unsigned (run 40123310737, sha256 fdb5fdfd…, core smoke ok on the runner) on the GitHub pre-release v0.31.0 (docs/features/electron/builds/0.31.0-*.md); cloud/tests_live 18 passed on Neon after migration 0003
- [x] C7 0.31.1 (operator's check on this Mac, 2026-10-24): the packaged app opened the working workshop with an empty window: the shell's CSP blocked the inline `<script>App.start()</script>` of index.html (the smoke only asked /api/health). Start moved to `ui/boot.js`; test in tests/test_desktop_shell.py; the smoke now loads the page under the policy and waits for the interface to draw; application icon (titanium oxide rings, packaging/make_icon.py). Windows build skipped for now at the operator's word.

## Review (2026-10-24, end of the electron goal's third stage)
- Done: stages A (0.29.0), B (0.30.0) and C (0.31.0) released, deployed on 8765 and attached to GitHub pre-releases; the cloud API on Vercel with Neon (migrations 0001–0003), the sign-in through Neon Auth's OAuth provider verified end to end against production.
- Spec: DEC-042..DEC-060 recorded (DEC-060 proposed, the rest as accepted in the session), REQ-080..087 criteria ticked as built; overview stays `implementing` while owner-resource criteria are open.
- Open for the operator: Windows code signing and macOS notarization (REQ-080 c2 public beta), minimum OS versions from clean machines (DEC-036), firewall and pairing on a real Windows machine (REQ-082 c6), a real-browser sign-in with Google from the application window (REQ-086 c5), account recovery on the cloud's sign-in page (REQ-086 c6), the terms on release cards confirmed on screen (REQ-086 c13).
- Lesson recorded in tasks/lessons.md: probe the real auth provider before designing against a fake.

# Vector work: photograph -> gapless colour regions -> titanium colours -> LightBurn (operator, 2026-10-19)

Requirements REQ-033 (split), REQ-034 (colouring, recolouring, file), REQ-035 (engraving time); decisions DEC-073 (all measured
colours, up to 29 with cleaning first), DEC-074 (recolouring modes, YuNet faces + manual areas), DEC-075 (time, filter, fastest
within tolerance), DEC-076 (proposed: superpixels + planar map of shared borders). Branch feat/vector-work-colours from origin/main.

- [x] V1 Segmentation core (worktree): smoothing + SLIC superpixels finer in important areas, Lab clustering to N <= 29,
      small-region merge, planar map of shared arcs smoothed once, holes, Path export from arcs; YuNet model shipped as
      package data with its licence; manual important areas; determinism; gapless test by rasterising (< 0.5 % gap/overlap).
- [x] V2 Time and colouring (worktree): time per cm2 / per cm from settings (DEC-075); colour map shows time and filters;
      search orders equal colours by time; palette = every measured colour of laser+lens+titanium; assignment modes
      nearest / tonality / random (seeded, restorable) / fewer layers; fastest within tolerance; per-group and per-region change.
- [x] V3 Vector work flow (main tree, after V1+V2): steps split -> preview -> colour -> preview -> file; important-area
      marking on the picture; variants kept; export cleaning first, <= 29 recipe layers, Paths from shared borders; job time.
- [x] V4 Tests green, real photograph through the flow (gaps measured on the export), PR, CI, merge, 0.5.0, deploy, walkthrough.
      1051 passed; CI green; v0.5.0 (#23) deployed after a backup; walkthrough on the Inna picture (work 21): face, eyes, lips
      found, 12 colours = 500 regions, export cleaning + 9 layers, 0 % gaps/overlaps, 3 h 54 min estimated. The walkthrough
      found the area overlay hiding the picture (chart style of svg[role=img]): fixed in v0.5.1 (#24), deployed, verified.

# Implement the whole specification (goal set 2026-10-18)

Branch `feat/titanium-color-engraving-intelligence-platform`, created from `origin/main` (5d31a9d) and fast-forwarded by the 20
unmerged commits of `feat/laser-device-profiles` (REQ-017..REQ-029). Baseline on the carried working tree: 561 passed, 0 skipped
(5 min 27 s). Spec read in full: 29 requirements, 61 decisions, 24 questions, 3 findings, discussion.md.

## Gap analysis (five read-only audits of every acceptance criterion, 2026-10-18)

Binding and not (fully) implemented:
- DEC-042 / Q-022 (B): laser profiles are still a NOT NULL foreign key on plate, plan, pair, observation, knowledge, target_color,
  proposal; the operator must create one before ingest, artwork, photo engraving, designer, calculator; "Профили" is in the menu.
  Imports take the profile's lens (REQ-016 AC3), servers default 200 ns (REQ-010 AC7), lens focal length NOT NULL (REQ-019 AC1).
- REQ-013 loop broken: a LightBurn file exported from a discrete / tonal / colour-path plan is refused at ingest ("experiment
  identifier TCE-A-/TCE-P- not known"), so no generated plan can be measured; marked works never align automatically.
- REQ-012: export writes recipe settings (layer type, bidirectional, cross-hatch, angle, ...) as defaults; the recipe key holds them.
- DEC-021: an alignment revision is stored as a re-photograph; accepting it leaves the engraving with 0 independent repetitions.
- DEC-047: knowledge is not rebuilt after a pair is deleted; a plan with active pairs can be cascade-deleted; plates never marked Deleted.
- DEC-027/028: capability-plate marker/label layers can become model-eligible observations on a charted photograph.
- DEC-034: "not comparable to this hardware/search setup: ..." (operator's printout 2026-10-18), every "... not found" (KeyError),
  api/ messages, matrix titles and layer names reach the screen in English; the coverage test cannot see them.
- REQ-004: colour-path has no per-plan inclusion of questioned sets in the UI; tonal warning links only the first entry.
- REQ-012: photo form defaults to 32 bands and says "1–255" (limit 28/29); the banding preview is a table, not a picture.
- REQ-009: no capture setup is recorded (a dummy "Photo capture (no rig)"); rig repeatability is never shown; DEC-025 chart
  reference values hard-coded instead of a capture-setup setting.
- REQ-005/006: imported files never become an EngravingPlan (MODE_RESTORED unused); a plate made for a target colour is never
  checked against it after measurement.
- REQ-019 AC6: artwork/photo plans take no lens snapshot; snapshots carry no spot basis.
- REQ-020 (I-11): no task kind on plans, plates, pairs or observations; no task filter; recommendations without counts/confidence;
  metrics without method/basis; provisional (checked, not accepted) pairs missing from the general colour map (DEC-045).
- REQ-029/DEC-021: colour-map search counts re-photographs as repeats, mixes chart and camera-relative points, merges batches.
- REQ-028: cancelled/superseded plates listed as "waiting for a photo"; the device tab keeps a second list of photographs.
- REQ-022 (I-13): no run-on-demand or scheduled analysis, no aggregated findings (improvement / anomaly / unstable / gap), findings
  history overwritten (AC6), proposals without question/hypothesis/context, no accepted state, plate -> pair -> result not linked.
- REQ-021 (I-12): no vectorisation (pixel runs -> rectangles at 160 px), only three strategies, no editing, no weak-evidence preview.
- REQ-030 (draft): nothing implemented; blocked by Q-025 (open).
- Designer (DEC-033 + DEC-042): one GP over six axes mixes job-setting groups; rules/targets keyed by raw profile id.
- Oxide (DEC-060, proposed): ignores model_eligible, mixes devices/lenses; /colors/settings gives computed settings without the
  three values of REQ-002.
- Small bugs: delete_device uninstalls the lens before refusing; device.js reads a pulse_width profiles never carry.

Spec contradicts itself (need the operator): chart/rig in every frame (REQ-001/003/009/013/015/024) vs accepted DEC-045/053;
REQ-003 "no plate without markers" vs unmarked small-patch plates (README); DEC-047 "rebuild" vs DEC-029 "never lower a stage";
DEC-013 "LLM never chooses parameters" vs the AI researcher that creates plates; DEC-048 vs proposed DEC-058; REQ-016 "material
optional" vs REQ-020 "titanium stock on every record"; DEC-028 "skip < 25 px" vs DEC-050 narrow-stroke fallback; DEC-008 free N vs
DEC-044 cap; DEC-029/033/041/056 still speak of profile versions after DEC-042.

## Plan (work packages; each ends with tests green and the spec updated)

- [x] WP-0 Branch from origin/main, baseline, CI installs tesseract (matrix OCR tests must not skip in CI).
- [x] WP-1 Spec reconciliation: answers and resolutions recorded as decisions in MarkView; plan.md status table; GitHub issues
      for I-11..I-13 and the new work items.
      Done 2026-10-18: DEC-058..061 accepted, REQ-030/031 approved, Q-025 answered (DEC-062), DEC-063 (full schema
      migration), DEC-064 (AI researcher exception), DEC-065 (contour vectoriser), DEC-066 (9 reconciliations); issues #13-#19
      (I-11..I-17), draft PR #20; plan.md items I-14..I-17 and statuses.
- [x] WP-2 Translations (DEC-034) and a coverage test that collects KeyError, api/ and wrapped messages.
- [x] WP-3 Closed-loop bugs: generated plans ingestible and auto-aligned (REQ-013), full settings on export (REQ-012), revision
      keeps its repetition (DEC-021), deletion rebuild and plan protection (DEC-047), marker/label never model-eligible
      (DEC-027/028), device delete, unreadable QR (REQ-003).
- [x] WP-4 DEC-042: no operator-managed profiles (approach per the operator's answer), device + lens + job settings everywhere,
      lens may be incomplete, imports do not assert the installed lens, 200 ns only as a device-supported prefill.
      Done 6bf303b: full schema migration (DEC-063), review found 0 critical / 5 major (all fixed); live-database copy: 662
      observations byte-identical; 580 passed. Startup refusal names the exact SQL fix (0.3.1 cannot re-link a profile with
      records). Next: three parallel streams in worktrees — S1 loop + ingestion (WP-3, WP-6), S2 export + conversion UI +
      vector job (WP-5, WP-10), S3 experiments + colour map + prediction (WP-7, WP-11); then WP-8, WP-9, WP-2, WP-12, WP-13.
- [x] WP-5 Conversion UI: band limits and banding picture, colour-path inclusion, tonal warning with all observations, lens
      snapshot with spot basis on every plan.
- [x] WP-6 Ingestion completeness: capture setup on upload, chart reference in the setup, rig repeatability shown, restored
      EngravingPlan for imports, target-colour check after measurement.
- [x] WP-7 Experiments and colour map: cancelled plates, one list, provisional pairs, honest search grouping.
      Streams merged 2026-10-18: S1 576e3c8..93d37a2, S2 f520c39..96a8ef5, S3 c177161..445df58; integration fix; 746 passed.
      Proposed decisions for the operator: DEC-067 (S2), DEC-068 (S3), DEC-069 (S1). The live app on 8765 was found serving
      the new UI against the old in-memory backend (it ran from the working tree); restarted from the installed wheel of
      59c4704 after a backup (lessons.md).
- [x] WP-8 REQ-020 task kinds end to end.
- [x] WP-9 REQ-022 findings and proposals loop.
- [x] WP-10 REQ-021 image -> vector LightBurn job (approach per the operator's answer).
- [x] WP-11 REQ-030 predicted look of a photo engraving (after Q-025).
- [x] WP-12 Designer and oxide model per comparable partition; REQ-002 values on computed settings.
- [x] WP-13 Tests for every criterion that has code but no test.
      Final: 909 passed (0 skipped); QR 0/1000 failures; pre-deploy check on an isolated full copy (database + files):
      16/16 experiments accepted as in the running app, every photo and overlay served, 565/565 colour-map points.
- [x] WP-14 Version 0.4.0, PR, CI, merge, tag, deploy (DEC-024), browser walkthrough, manual checklist.

## Review (2026-10-19)

- PR #20 merged (5c5208f), CI green on Linux 3.11/3.12 and macOS 3.12; tag v0.4.0; issues #13-#19 closed by the merge.
- Tests: 909 passed, 0 skipped. QR identifier read for 1000 of 1000 synthetic codes (classic detector alone: 991).
- Deploy (DEC-024): backup titanium-before-deploy-0.4.0-20261019T001137Z.sqlite, wheel from the tag installed in
  ~/.titanium-platform-app, port 8765 answers 0.4.0; the migration made titanium-before-0.4.0-20261019T001151Z.sqlite.
  Live data after the migration: 662 observations byte-identical to the backup, 16 experiments accepted, every photo
  and overlay served, 565 colour-map points, all 39 pairs on laser 1 with lens 2.
- Walkthrough in the operator's tab: a tab opened before the upgrade showed the old page ("Не найдено") until reloaded.
- Open for the operator: proposed DEC-067..DEC-072; LightBurn opening of exported files; tablet access; a .lbrn sample.

# New experiment kind: a parameter matrix (LightBurn Material Test) read from its photograph — goal set 2026-10-18

Operator: photographs of colour matrices; every square is engraved with its own settings, the settings are engraved as text, two
parameters vary along the two axes. Samples: IMG_3300 (power x speed, 250 kHz 9 ns), IMG_3301 (power x speed, 330 kHz 4 ns), IMG_3302
(power x speed, 60 kHz 300 ns), IMG_3304 (power x interval, 1950 kHz 2 ns), IMG_3305 (1-D: Q-pulse 1..10 ns and passes 1..5 at 40 %),
IMG_3306 (1-D: interval 0.001..0.005 at 40 %). All carry a ColorChecker and a ruler; all are 1.5–3.8 stops under-exposed.

Design: the matrix becomes an ordinary pair whose LightBurn file is generated from the recognised grid and the confirmed settings (one
Scan layer per cell), so the check, the masks, acceptance, observations, the colour map and the oxide model work unchanged.

- [x] 1. `photo.correct`: detect the chart on an exposure-normalised rendering of the linear decode (prototype: found on 6/6, residual
      2.8–3.6 dE; on the 8-bit decode 1/6).
- [x] 2. `matrix.py`: square cells -> lattice (lattice -> px) -> grid extent (cell vs gap contrast, uniform interior, connected to the
      detected squares) -> rectified grid -> labels (row numbers left, column numbers below rotated, header above, axis titles) read with
      tesseract when it is installed (an optional system program, no new Python dependency) -> interpretation: fixed settings from the
      header, the two varying parameters from the axis titles / what the header lacks, axis values as an evenly spaced sequence fitted
      robustly to the labels that were read (misreads repaired, at least 3 consistent labels) -> rows/cols trimmed or extended by labels.
      Several matrices in one photograph: every complete one is a candidate.
- [x] 3. Generated LightBurn file (cell pitch 5 mm by default; settings tags as the parser reads them) and the alignment of a matrix pair
      straight from the lattice (method "material test grid").
- [x] 4. Ingest: create a matrix pair from a photograph (+ laser profile, titanium), edit the spec (axis parameter, min, max, count, fixed
      values) which regenerates the file and re-checks, confirm the spec; acceptance refuses an unconfirmed or incomplete spec.
- [x] 5. API + UI: upload mode "Матрица параметров" (photo only), the matrix card on the review screen (what was read, editable spec,
      confirm), other matrices of the same photo offered as their own experiments; experiment list names the kind.
- [x] 6. Tests: synthetic material-test photograph (grid, labels, chart, under-exposed) -> detection, interpretation, repair of misreads,
      generated file round trip, whole path to observations; OCR tests skip without tesseract.
- [x] 7. The six real photographs through the application; numbers here; DEC + REQ in MarkView; full suite.

## Film order along a matrix, kinetics per pulse regime (PROPOSAL, awaits the operator's approval)

Finding (2026-10-18, operator's paste of the "settings for a colour" card): the kinetics gives no settings although the
matrices are exactly the dose ramps its note asked for. Measured on the live store:

| regime | cells with dose | thickness determined | Spearman thickness~dose | power law r2 |
|---|---|---|---|---|
| 1950 kHz 2 ns (IMG_3304, 3306) | 112 | 48 | 0.02 | 0.003 |
| 330 kHz 4 ns (IMG_3301) | 107 | 50 | 0.50 | 0.035 |
| 250 kHz 9 ns (IMG_3300) | 106 | 11 | 0.72 | 0.31 |
| 60 kHz 300 ns (IMG_3302) | 0 | — | — | — |

- Cause 1: the thickness is fitted to each colour on its own. In IMG_3301 the palest cells (almost bare titanium) get 96 nm,
  neighbours jump 96 / 226 / 126 / 274 / 400 nm, while the colours run smoothly pale -> gold -> purple -> blue -> teal with dose.
- Cause 2: IMG_3302 has no dose: 300 ns is not a pulse step of the JPT M7 passport (… 250, 350, 500). Question to the operator:
  which pulse did the laser actually fire for "Q-Pulse 300 ns"?
Approved by the operator 2026-10-18 ("Да, делай"); the IMG_3302 pulse: "Не знаю" (the manufacturer's note in the device
template: a width that is not a step is ignored and the laser keeps the last valid one, so the fired pulse is unknown; the plate
stays on the colour map and out of the kinetics).
- [x] 1. Ramp-wide film order (`oxide.assign_ramps`, dynamic programming over the dose order, lightness weighted 0.35). Works on
      model-generated ramps (tests). FAILS on the real matrices, so it is OFF (`ORDER_BY_RAMPS = False`):
      | variant | IMG_3301 palest cells | path | median coloured residual |
      |---|---|---|---|
      | per cell (current) | 96 nm | jumps 96/226/126/400 | 4.87 |
      | ramp, plain dE | 96 nm | 96 -> 126 -> 228 -> 398 | 6.84 |
      | ramp, lightness 0.35 | 14 nm | 14 -> 126 -> 226, skips gold/purple/blue | 7.65 |
      | ramp, gain up to 2.2 | 20 nm | purple/blue cells 60-90 % dark oxide | 3.62 |
      | ramp, gain 1.6 + flare 0.1 | 10 nm | 10 -> 14 -> 210, purple/blue undetermined | 3.07 global, 4.23 after |
      Cause: the model's first-order colours are much darker and more saturated than the measured ones (model purple 36 nm
      L 27 b -22, blue 44 nm b -47; measured purple L 40 b -13, blue L 44 b -19); the paler second order wins. The "usable"
      laws the ramps produced (r2 0.6-0.85, exponents 2-5.6) are artefacts of the monotone constraint.
- [x] 2. Kinetics per pulse regime (`regime_laws`): in place; on the per-cell thicknesses no regime is usable (r2 0.31 / 0.04 / 0.003).
- [x] 3. Settings for a colour per usable regime (`_by_regime`: dose from the law, the nearest measured cell, the power that
      reaches the dose): in place, shows nothing until a law is usable. The colour card shows it.
- [x] 4. Tests: monotone path, ramp placement, per-regime laws, power search; 6 new / updated in tests/test_oxide.py.
- [ ] NEXT (needs the operator's approval): make the film model reproduce a measured ramp before ordering by it: thickness
      non-uniformity within a cell (spectra averaged over d +- sigma, which washes out the higher orders and the saturation),
      a specular gain above 1 and a flat flare, fitted on the matrices. Acceptance: on IMG_3301 the cells run pale -> gold ->
      purple -> blue in the first order (10-70 nm) in dose order, median coloured residual <= 5 dE, exponents of the laws
      0.2-1.5; only then ORDER_BY_RAMPS on.
- Alternative without physics (needs approval: the photo engraving deliberately does not interpolate): settings for a colour
  from the matrices directly, the nearest cell and interpolation between neighbouring cells of one matrix.
- Today already: for a colour the matrices produced, the colour map gives the measured settings (e.g. a blue L 55 b -25:
  a matrix cell at dE 1.7, obtained in 3 experiments).

## Fixes from the same paste (done 2026-10-18)
- [x] "null" above the film card: the DOM's replaceChildren prints a null child; `App.fill` skips them like `h()`. Same flaw
      fixed on the experiment page (the new matrix block) and the photo-engraving form. Static test guards every screen.
- [x] The kinetics and colour notes reached the screen in English: the translation coverage test now also collects
      `{"note": ...}` literals and conditional messages; translations added. The kinetics note no longer asks for ramp plates.
- [x] Verified in the browser: colour search without "null", Russian note; matrix table on the experiment page.

## Results (2026-10-18)

| photo | matrix | read | missing / wrong |
|---|---|---|---|
| IMG_3300 | 10 x 10 power 20->60 % x speed 1500->500 mm/s, 250 kHz 9 ns 0.002 mm 1 pass | complete | — |
| IMG_3301 | 10 x 10 power 25->50 x speed 1500->300, 330 kHz 4 ns 0.003 mm 1 | complete | — |
| IMG_3302 | 10 x 10 power 5->30 x speed 150->50, 60 kHz 300 ns 0.0169 mm 1 | complete | — |
| IMG_3304 | 10 x 10 power 10->100 x interval 0.010->0.001, 1800 mm/s 1950 kHz 2 ns 1 | complete | — |
| IMG_3305 | 1 x 10 Q-pulse 10->1 ns at 1800 mm/s 1950 kHz 1 pass; + a 1 x 5 passes column | rows, speed, frequency, passes | power (label cut by the plate edge), interval (overprinted); the second column's labels |
| IMG_3306 | 1 x 5 interval 0.005->0.001 at 40 % 1800 mm/s 1950 kHz 2 ns | all | passes read 4 instead of 1 |

- Through the running application (POST /matrix-pairs + check): pairs 52–57 created with laser profile 1 and Big Plate 150 Grade 5,
  100 / 100 / 100 / 100 / 0 / 5 cells measured, chart residual 2.8–3.6 dE.
- On the colour map (operator's remark "add the results to the colour map"): every read setting was compared with the engraving on
  the chart-corrected overlay; 3306 passes corrected 4 -> 1 (the header reads "Passes: 1"). Accepted: 52 (by the operator), 53, 54, 55,
  57 (the operator replaced 57 by its re-check 58 with the same settings). 405 calibrated points of matrices on the map (555 in all).
- IMG_3305: the first pair (56) was deleted by the operator. Re-created as pair 59 (unconfirmed, 10 / 10 cells measured):
  interval 0.0030 mm read by eye under an overprinted faint label column; power 40 % proposed, NOT read: the column label is cut by
  the plate edge, only its last "0" is visible. Cross-check of its 2 ns cell against the same settings elsewhere (CIE76):
  IMG_3304 interval 0.003 at 30 % 8.8, at 40 % 8.2; IMG_3306 at 40 % 12.5; the same setting on 3304 vs 3306 differs by 5.7,
  so 30 % and 40 % cannot be told apart by colour. Verified afterwards from IMG_3306: the same Q-pulse plate lies there turned by
  90 deg at the right edge with "1.00", "2.00" and the complete power label "40.0" (a seam between two plates runs through the
  label, which is why IMG_3305 shows only its last "0"); its 1 ns and 2 ns cells match the IMG_3305 cells within dE 1.4 and 1.9,
  the crossed pairs differ by more than 10. The operator confirmed and accepted pair 59 at 40 % (17:58). The pair's stored note
  still says "proposed, not read"; the application has no way to edit a pair note and no screen shows it.
  The second matrix of the photo (1 x 5 passes at 40 %) has its interval and Q-pulse outside the photograph; not created.
- All six examples accepted: 415 matrix colours on the map, 565 in all.
- Oxide model refitted on 448 calibrated observations: median coloured residual 4.89 dE (goal < 5). Kinetics: still no single law
  (r2 0.01 on 111 points); the matrices are ramps at a fixed pulse regime, so a law per regime is the next step (needs approval).
- Chart on an exposure-normalised rendering: found on 6 / 6 sample photographs (before: 1 / 6).
- Tests: `tests/test_matrix.py` (15: geometry, dark chart, cut matrix, label fits, header, interpretation, OCR on a synthetic matrix,
  generated file, image->mm, edit, whole path to observations, refusals). DEC-061 and REQ-031 in MarkView (proposed / draft).

# Oxide thickness model, kinetics, settings for a colour, colour map — approved 2026-10-18 ("выполняй все по порядку")

- [x] 1. `oxide.py`: thin-film model (air / TiO2 film / titanium, Fresnel at the capture angle, D65, CIE 1931 2 deg -> Lab) with two
      mechanisms: an interference film of thickness d and a share f of absorbing dark oxide; global parameters (film index scale, film
      absorption, gloss, angle) fitted on every calibrated observation; per observation: thickness, dark share, residual dE, and whether
      another interference order fits almost as well. Success: median dE < 5 on the coloured regimes. API `GET /oxide/model`, tests.
- [x] 2. Kinetics: dose features from the layer settings and the device (average power, pulse energy, pulses per spot, line overlap);
      thickness and dark share against dose on the calibrated points; a monotone law fitted and its residual reported; `GET /oxide/kinetics`.
- [x] 3. Settings for a colour: `POST /colors/settings` with a target Lab -> nearest measured observations (as now) + model candidates
      (thicknesses of every order within tolerance -> dose -> power for every measured mode), each marked measured / computed with its
      expected error; shown in the colour map's search panel.
- [x] 4. Colour map: a lightness band control (L* range) and the three Lab projections; a settings card for the picked point with its
      neighbours in settings; the model's thickness spiral drawn under the points.
- [x] 5. Full suite (540 passed), the map and the three endpoints checked on the live data, DEC-060 in MarkView.

## Results (2026-10-18)

- Model (`oxide.py`, DEC-060 proposed): fitted on 43 chart-corrected observations: index scale 1.0, film absorption 0.05, gloss 1.0,
  angle 0. Coloured regimes (32): median residual 3.6 dE (goal 5), p90 9.5; dark regimes (11): median 1.1 dE through the dark-oxide share;
  70 % of all points within 5 dE; 25 points admit a second interference order within 3 dE; 15 thicknesses determined outright.
  Readings: golds 100–130 nm (first order) or 224–232 nm (second), blues 58–88 nm, purples ~272–282 nm, "black" = dark oxide 70–90 %.
- Kinetics: areal energy of the settings against thickness on this set: r2 0.07 -> no usable law (finished works mix 4 ns / 9 ns / 200 ns
  regimes and frequencies). The settings card therefore offers measured films only. Needed: plates with a monotone dose ramp at one
  pulse width and frequency, photographed with the chart.
- Settings for a colour: `GET /colors/settings`: thickness candidates in every fitting order, the measured settings that produced films
  within 15 nm (e.g. gold L* 72 b +34 -> 226 nm -> Kalinin C08/C12 40 % 1800 mm/s, Chicago C08 45 % 1600 mm/s, C05 24 % 1500 mm/s),
  reachability (within 8 dE of the spiral), the kinetics note.
- Colour map: planes a*b*, a*L*, b*L*; lightness band; the film spiral with thickness marks under the points; film reading of a picked
  point; film card under the search results.
- Tests: `tests/test_oxide.py` (8). Full suite running.

# Predicted look of a photo engraving from its picture and settings — plan awaiting approval (2026-10-18)

Operator: "for colour photo engraving the grey level sets the power; I want you to compute how the picture will look for the
parameters we set".

## What exists

- DEC-057: power = Min + (Max - Min) x (1 - grey) for a grayscale-mode image layer; `lightburn.py` reads the picture (PNG), the layer's
  Min/Max, speed, frequency, pulse width, line interval / dpi, passes and the picture adjustments (gamma, contrast, brightness, enhance).
- `ingest._tonal_profile`: for an accepted photo engraving, grey -> power -> measured Lab in 16 bins (pair 22, Inna: 13 bins, grey 0.16..0.91,
  power 6.0..14.4 % at 300 ns, 60 kHz, 128 mm/s, 1503 dpi). Each bin is a colour on the map with the settings of that power.
- 76 flat-fill observations (Scan layers) with full settings; `model.predict_for_lab` works the other way (colour -> settings).
- The screen "Непрерывная фотогравировка / Тональный" builds bands from validated plate colours; it does not take a LightBurn picture.

Prototype (scratchpad `inna_preview_proto.jpg`): the Inna picture rendered through its own measured profile. The mechanics work; the
result is nearly black because that photograph was dark and camera-relative (L* 1.4..7.2). The prediction can only be as good as the
measured evidence: today one dark photo engraving and no plate at these settings.

## Steps

- [ ] 1. `prediction.py` (new): `tone_curve(store, settings, profile)` — for a mode (speed, frequency, pulse width, line interval, passes,
      material, setup) collect every referenced measurement at that mode as (power, Lab, source): tonal-profile bins of accepted photo
      engravings and flat-fill observations; sort by power; the curve is linear in Lab between neighbouring measured powers; outside the
      measured span nothing is predicted (REQ-003). Camera-relative evidence is used only when nothing referenced exists, and is flagged.
- [ ] 2. `prediction.render(picture, settings, curve)` — grey of the stored picture -> LightBurn's adjustments (gamma, contrast, brightness:
      standard formulas, marked "assumed"; enhance / denoise not modelled) -> power (DEC-057) -> Lab from the curve -> sRGB. Returns the
      image, a coverage mask (predicted / outside the measured span / no evidence), the share of pixels outside, the curve used with the
      provenance of every point, and whether the colours are referenced or camera-relative. Dithered modes (Stucki, Jarvis, threshold) are
      refused with a reason; only grayscale mode is predicted.
- [ ] 3. API: `POST /predictions/photo` takes a LightBurn file (the picture and the settings are inside) and optional overrides
      (min_power, max_power, speed, frequency, pulse width, line interval) -> JSON (curve, coverage, flags) + `/predictions/photo/{id}.png`
      (preview, side by side with the picture, hatched where not predicted). Nothing is stored except a short-lived cache of the upload.
- [ ] 4. UI: screen "Предпросмотр фотогравировки": upload the LightBurn file, per image layer the picture next to the predicted look; sliders
      for Min/Max power that re-render; the curve table (grey -> power -> colour, source of each point); a plain statement of what the
      prediction rests on (which plates / pairs, referenced or camera-relative) and what it does not know (powers outside the span).
      A link from an accepted photo engraving's experiment page ("как будет выглядеть при других Min/Max").
- [ ] 5. Tests: curve from synthetic observations (interpolation, span limits, flags), render of a synthetic picture, refusal of dithered
      modes, API round trip, i18n coverage.
- [ ] 6. Real check: the Inna file through the screen; the prediction against its own photograph (self-consistency) and the picture's
      5.5 % of pixels outside the span reported.
- [ ] 7. MarkView: REQ "predicted look of a photo engraving" (draft, waiting for approval), decision on the evidence rule.

## Decisions needed from the operator

1. Evidence: is a prediction from camera-relative photographs (no ColorChecker, as all pairs so far) acceptable when flagged, or should the
   screen refuse until a referenced measurement at that mode exists?
2. Picture adjustments: predict with standard gamma / contrast / brightness formulas and say "assumed", or refuse files whose picture
   adjustments are not at LightBurn's defaults?
3. Scope of v1: grayscale mode only (dithered modes refused), LightBurn file as the only input (no bare picture + typed settings).

# Automatic alignment refused on the operator's new pairs (2026-10-18) — approved: rewrite the start without the frame (operator, 2026-10-18: "перепиши все")

Operator: "match does not work" (CowBoy, lion, limitless). Reproduced on the real files, outside the application.

## What fails and why (measured)

| pair | automatic result | cause |
|---|---|---|
| CowBoy (pair 24, deleted) | "no frame window was found" → manual corners | black parts of the work touch the frame at the top and right; `find_window` requires half of the scan lines of a side to end on one line (top 25/60, right 23/54) |
| limitless (pair 25) | "no frame window was found" | window is found at 1100 px but refused at the working scale (2194 px): the line tolerance is 3 px regardless of the scale, and glossy black frame edges end the dark run early on 10–25 % of the lines |
| lion (pair 23, **accepted**) | anchoring refused "orientation ambiguous" (0.056 vs 0.058 mm); the old geometry fallback accepted 3 shapes with residual 0 and a mirror | the drawing is dense (30 % of the window pixels are edges), so the trimmed-50 % cost is ≈ 0 for every orientation; the plain capped mean separates the true orientation 3× (0.067 vs 0.186 mm). **The fallback overlay is wrong (checked visually): the 19 observations of pair 23 were measured off the drawing.** |

Prototype (scratchpad, no repository change): with a dominant-line rule in `find_window` (tolerance 0.3 % of the long side, at least 25 % of the lines, outermost of near-equal lines) and the plain capped mean as orientation cost:
CowBoy → element anchors, 31 anchors, residual 0.06 / 0.12 mm (median / p90), spread 0.54, orientation margin 0.62, 5 s;
unbreakable (pilot) still → 64 anchors, 0.07 / 0.12 mm, margin 0.39.
lion and limitless need the final line rule (a hard "no points outside the line" filter rejected their glossy frames); to be verified in step 1.

A start without any frame (whole drawing searched over 8 orientations × scale × shift on the current coarse grid) fails on all four pairs: the grid is built for a start near the truth. A frame-less start needs a coarse-to-fine (pyramid) search — a separate step, see 5.

## Steps (approved)

The start of the registration no longer needs a frame. The whole drawing is searched in the photograph; the frame window is derived
afterwards from the known plate size and the lightness step at its edge, and is used only to say what is hidden.

- [x] 1. `anchoring.prepare`: edge map with the gradient direction of every edge pixel (4 direction bins, each bin also accepts the two
      neighbouring directions), so that a dense drawing of parallel strokes cannot match itself turned by 90 degrees.
- [x] 2. `anchoring.global_search`: at a coarse resolution (long side 480 px) the drawing's outline samples, with their tangent
      directions, are rendered as a 4-channel template for every pose (mirror x 4 right angles x small rotation offsets x plate
      scale 0.3..1.1 of the photograph) and correlated with the proximity map (FFT); best shift per pose; the best pose per
      orientation is kept. Score = mean proximity over all outline points, so a cropped photograph lowers every orientation alike.
- [x] 3. Every orientation's best pose is polished at 1100 px by coordinate descent on the plain capped mean distance (no trimmed
      share); ranking by the polished cost; the two best go to the element matching at the working scale (10 px/mm) exactly as
      before (`_refine`, RANSAC fit, anchors-of-the-second-orientation gate, inlier / residual / spread gates).
- [x] 4. `anchoring.window_from_frame`: with the final transform, each side of the plate rectangle is scanned for the inner edge of
      a dark frame within 3 % outside .. 12 % inside; the dominant line per side (>= 25 % of the lines, tolerance 0.1 mm,
      outermost of near-equal lines); a side without a frame edge is the plate edge itself. No frame = nothing hidden.
- [x] 5. `ingest._align`: the geometry fallback result must be supported by the photograph's edges (`anchoring.outline_support`)
      or it is not used; a wrong three-shape fit (lion) yields "place the four corners" instead of a mirrored overlay.
- [x] 6. Tests: synthetic work without a frame is registered and nothing is hidden; a black silhouette touching the frame; a
      drawing of parallel strokes; the geometry guard; i18n coverage; existing suites green.
- [x] 7. Real pairs through `anchoring.register` and through the application: unbreakable, lion, CowBoy, limitless, Inna (picture
      route untouched); numbers recorded below.
- [x] 8. MarkView: decision "the frame is derived from the plate, not required" (supersedes the frame-window part of DEC-049);
      pair 23 (lion): re-check and, with the operator's consent, delete its 19 observations.

## Results (2026-10-18, real pairs through `anchoring.register` and through `check_pair` on a temporary store)

| pair | method | anchors | residual median / p90 mm | orientation margin (cost best/second) | frame hidden per corner mm | time of the check |
|---|---|---|---|---|---|---|
| unbreakable (pilot) | element anchors | 72 | 0.066 / 0.131 | 0.77, second orientation 6 anchors vs 72 | 3.3 · 0.4 · -1.4 · 1.4 | 20 s |
| lion | element anchors | 26 | 0.077 / 0.158 | 0.56, second 0 anchors | 2.7 · 2.8 · 2.0 · 1.7 (bottom side = plate edge) | 18 s |
| CowBoy | element anchors | 27 | 0.072 / 0.136 | 0.78, second 0 anchors | 3.8 · 4.3 · 3.7 · 0.6 | 17 s |
| limitless | element anchors | 41 | 0.123 / 0.176 | 0.52, second 17 anchors vs 41 | 3.9 · 7.2 · 0.6 · 1.1 | 34 s |
| Inna (picture route) | picture | — | — | untouched | 3.8 / 5.3 mm left / right | 9 s |

`anchoring.register` alone: 8–9 s per pair (global search 240 px, 8 direction bins; the polishing pyramid; element anchors at 10 px/mm).
A negative hidden margin means the frame edge lies outside the file's rectangle (the physical plate is larger than the C00 rectangle).

Lion, corrected: the whole-shape fit of pair 23 was not mirrored but off by 0.4 mm (median) and up to 2 mm at the edges against the
anchored result; `anchoring.confirm` from that fit converges to 23 anchors, residual 0.063 mm. Two anchored results of the lion (from the
global search and from the whole-shape start) differ by 0.43 mm median, 0.78 mm max: that is the real accuracy on a drawing of dense
parallel strokes, wider than the anchor residual says. The plate-corner uncertainty reported to the operator (0.24–0.37 mm) is of that order.

Synthetic: a work without a frame is registered and hides nothing; a black silhouette on two plate edges leaves the frame edges where
they are (hidden 1.5–3.6 mm on every side, accuracy < 0.4 mm); a drawing of parallel strokes is registered mirrored as photographed;
a start from another route is confirmed when right and refused when mirrored.

The application server was restarted on the new code on 2026-10-18 (port 8765, log in ~/.titanium-platform/server.log). Full suite: 530 passed.

## Re-measurement of every chart pair and the first thin-film result (2026-10-18)

- Operator: re-check every experiment; works without a chart will be re-photographed with it. Done through the running application for
  every accepted chart pair (alignment revision -> fresh automatic check -> masks reviewed -> accepted; the superseded pair is retired by
  `accept_pair`): Motorcycle 1, Van Gogh (CowBoy), Sergey Kalinin, ChicagoGirlShow, Soccer Players, Girl on a bike -> pairs 46–51, chart
  residual 3.6–4.2 dE, grey ramp within 1–3 L*, 44 observations. Still camera-relative, waiting for a photograph with the chart:
  unbreakable (IMG_3281), Inna (IMG_3283), lion (IMG_Lion), limitless (IMG_Limitless).
- Thin-film prototype (`scratchpad/thinfilm.py`): air / TiO2 film (Cauchy n ~2.3–2.5) / titanium (n,k from the literature), Fresnel at the
  given angle, D65, CIE 1931 2 deg -> Lab; free parameters: index scale, film absorption, gloss (overall reflectance factor), angle. Fit of
  the 43 calibrated observations: best gloss 0.7, angle 30 deg, median 8.9 dE, 30 % within 8 dE. The coloured regimes (gold 19–130 nm, blue
  58–88 nm, purple ~280 nm) sit on the curve within 3–9 dE; the dark neutral "black" regimes (L* 35–38, chroma < 4) are 21–23 dE off: a
  pure interference film cannot be dark and neutral, that is an absorbing, rough oxide, a second mechanism. Thicknesses above ~200 nm are
  ambiguous (the curve loops). Next: proper n,k tables, a two-mechanism model (interference + absorbing fraction), fixed capture angle on
  the stand, and plates with a monotone dose ramp to order the points along the spiral.

## "Again no black" (2026-10-18): the black is C01 at L* 34–38; the witness of a fully engraved plate was a fallback artefact

- On the ChicagoGirlShow photograph the darkest pixels of the plate are L* 32–35 (99 % of them in layer C01); the chart's black patch in the
  same frame is L* 22 (3.6 % reflectance), its dark grey patch L* 36.5 (9.3 %). The engraved "black" reflects 8–9 %: it is the chart's dark
  grey, not its black. The table is right; there is nothing darker on the plate.
- Defect found on the way: the first layer C00 (68 %, 1000 mm/s, the whole plate) is engraved over entirely, so its clean-witness mask was
  empty; the measurement then fell into the narrow-stroke fallback and reported L* 50 over 8.9 M pixels as "clean titanium". Operator's
  rule (2026-10-18): clean titanium shows only where no fill covers it, and every layer counts. Now: an entirely covered witness is not
  measured and says so; the witness is sampled wherever no later layer engraved, with a 1 mm guard around every later outline and the
  plate edge instead of shrinking the plate rectangle by 20 % of its side (which had hidden the clean ring at the edge); a first layer
  that measures dark or coloured (L* < 50 or chroma > 15) is a background fill, measured as a colour, and the photograph has no clean
  reference. Soccer: clean titanium between the players L* 80.4 over 4.5 M px; Sergey Kalinin: first layer covered entirely.

## "Why no black" (2026-10-18): colour measured from a 16-bit linear decode (DEC-059, proposed)

- The black layer of ChicagoGirlShow (C01) measured L* 28: its mask is clean (5th percentile 23, ruler 1 % of pixels), the darkest point of
  the plate is L* 22. The black oxide is a dark grey of about 5 % reflectance, like the chart's black patch (3 %, L* 21.7).
- But the chart correction distorted the dark tones: grey ramp after the matrix 99.9 · 82.4 · 65.1 · 46.5 · 28.3 · 13.4 against the reference
  95.8 · 80.6 · 65.9 · 51.2 · 36.1 · 21.7. Cause: the RAW developed to 8 bits with a tone curve was read as sRGB; the darks were up to 3x too dark.
- Change: `photo.decode_linear` (16-bit, gamma 1, camera WB), chart patches read from the linear image (`chart_patches_linear`), matrix fitted
  in linear light (`fit_correction_linear`), corrected and camera-relative colours and the clean-titanium ratio from the linear image; the
  check reports the grey ramp (`chart.grey_ramp`), the review screen shows it. The 8-bit decode stays for detection, alignment, previews.
- Six chart pairs re-checked on a temporary store: residual 6.0–6.5 -> 3.6–4.2 dE; grey ramp within 1–3 L*; black layers L* 25–28 -> 35–38,
  mid tones +4–8, light tones +2–5, chroma almost unchanged. Pairs 30–37 (and all camera-relative ones) carry the old bias: re-measure as new
  pairs. Tests: photo, ingest, framed, picturing green.

## Motorcycle 1 (IMG_3294, photo engraving with the chart): the picture route starts from the global search too

- Cause: the picture route's start was a small grid of sizes (0.8–1.1 of the short side) and positions (±12 %) built for close-ups; a plate
  photographed with a chart and a ruler beside it is smaller in the frame and off-centre, so no start was near and the ECC refinement
  ended at a correlation of 0.13 (0.25 required). Widening the grid alone broke the Inna close-up: the 128-px edge correlation does not
  rank starts reliably across scales.
- Rule: the picture's edges (Canny on the stored grey, with their tangent directions) are searched exactly as the vector outlines are
  (`anchoring.global_search`, scale 0.3–1.5 of the photograph, every shift, mirror and right angles); the best pose of each of the four
  best orientations is refined with ECC and the refined correlation decides. Motorcycle 0.55 (second 0.12), girl on a bike 0.53,
  Inna 0.33 with the same hidden margins as before. Picture route ~10–12 s.
- Open: a light grey frame (motorcycle) gives no step of lightness at its inner edge, so the window is not found and 6 % (9 mm) per side is
  assumed hidden; the measured surface loses that band. The frame edge of a light frame needs a texture or edge criterion, not a step.

## Photographs with a ColorChecker and a ruler (2026-10-18): IMG_3293..3297, checked outside the application

- Chart found on all five (OpenCV mcc, 24 patches, 0.3 s each), correction residual 6.1–6.5 dE (limit 12); white patch as shot 98–133 of 255,
  so the shots are ~1.3 stops under at the chart, acceptable. The ruler is not used by anything and does not interfere.
- Full check on a temporary store: Soccer (IMG_3293, unframed plate on the textured background) → chart-corrected, element anchors, 32
  anchors, residual 0.057 / 0.134 mm, clean titanium L* 78.8, gold half-shirt L* 68 b +38; CowBoy (IMG_3295) → 51 anchors, 0.093 / 0.142 mm,
  gold L* 69 b +54. IMG_3294 (motorcycle), 3296 (girl on a motorcycle), 3297 (man's portrait) are new works without a pair yet.
- Two refinements the bright Soccer photograph forced: (1) every orientation whose polished cost comes within the 0.9 margin of the best
  goes on to the anchor stage (at least two, at most three) instead of a refusal there; (2) when the mirror twin keeps half the anchors
  and the outline support is within 0.05, the elements that only one orientation explains (>= 70 % of their outline vs < 50 %) decide:
  the best needs at least 3 and three times the twin's. Soccer bright: 9 vs 1; dark: 20 vs 0; the other pairs 154–378 vs 0. A drawing
  that anchors nowhere while every orientation looks alike is refused as ambiguous (nested squares).

## "Light colours are not found" (2026-10-18): camera-relative colours against the clean titanium of the same photograph

- Cause: a photograph without a chart is measured as the camera exposed it (RAW decoded with no brightness change). The operator's
  photographs are 2.5–5 stops under nominal (sensor median 1–3 % of white; Soccer: clean titanium at L* 9.4), so every colour came out
  nearly black and the light ones could not be told.
- Rule (DEC-056 carried from the colour map into the check): where the work's cleaning layer shows clean titanium in the same photograph,
  every measured colour is also given as it would look next to nominal clean titanium: the ratio to the clean surface per channel in
  linear light, which does not depend on the exposure. Derived on every read (`ingest.express_against_clean`), never stored; the
  camera-relative value stays as the evidence. Experiment, analysis and layer dialogs show the derived colour first, "как снято" beside.
- Soccer (pair 29): gold half-shirt C08 as shot L* 6.7 b 6.7 → L* 58.5 b 28.7; blue C10 L* 5.1 b -7.0 → L* 53.1 b -31.8; exposure
  5.2 stops under. Nominal clean titanium is the default L* 68 until a photograph with a chart measures it.
- Not covered: works without a cleaning layer (Inna's photo engraving) stay as shot; the photographs should be exposed for the metal.

## Soccer Players (2026-10-18, after the rewrite): two rules added

- Four identical shirts: the mirrored orientation also collects anchors (29 against 22), so the anchor count cannot decide. Rule: when the
  second orientation keeps >= 50 % of the anchors, the orientations are compared by the share of the *whole* outline the photograph
  confirms (edges of the right direction within 0.15 mm); the best must lead by 0.05 or the work is refused. Soccer: 0.857 vs 0.721, checked
  on the stripes of the second player's shorts at full resolution. Lion 0.91 vs 0.24, unbreakable 0.73 vs 0.24, CowBoy 0.78 vs 0, limitless
  0.78 vs 0.12.
- The strictest refinement pass kept 8 anchors of 162 elements (the engraved edges are doubled by a dark rim, which fails the
  distinctiveness test at a 0.4 mm radius) while the first passes had 38–57. Rule: after the passes, every element with a close,
  distinctive match within 0.5 mm of its prediction under the final transform is an anchor. Soccer: 22 anchors, residual 0.042 / 0.119 mm,
  spread 0.42. The other pairs gained anchors (unbreakable 106, lion 34, CowBoy 51, limitless 83) at residuals 0.09–0.10 / 0.15–0.18 mm.
- Soccer's plate is engraved dark to its edge, so no frame edge is found: nothing is reported hidden, which is right for that photograph.

# Element-anchored registration of unmarked works (framed artwork)

Branch: `feat/laser-device-profiles`. Goal (user, 2026-10-16): the photograph of a finished work is aligned to its
LightBurn file by finding a few reliable elements, trusting them, and computing every other element from the file
distances. Parts hidden under a frame are inferred, never measured.

Pilot pair: `unbreakable.lbrn2` (19 layers, 235 closed vectors) + `IMG_3281.DNG` (framed, no reference chart).
Prototype with measured results: session scratchpad `proto/` (coarse 8-orientation search, per-element anchors,
robust homography, hold-out test).

## Scope

- [x] 0. Record the decisions in MarkView first (DEC element anchors, DEC frame window, REQ registration, REQ exact geometry).
- [x] 1. `lightburn.py`: exact vector geometry (Bezier edges, sub-paths, holes, closed flag per loop).
- [x] 2. `photo.layer_mask`: honour holes of a shape.
- [x] 3. New module `anchoring.py`: edge map, frame window, orientation search, element anchors, robust fit, classification, uncertainty.
- [x] 4. `ingest._align`: use anchoring before `register_geometry` for unmarked works; manual four corners stay the fallback (REQ-013).
- [x] 5. Measurement: the frame window limits the visible surface; partly hidden elements are measured on their visible part only.
- [x] 6. Overlay + review report: statuses (anchor / confirmed / computed / hidden), hidden margins, orientation margin.
- [x] 7. UI strings (ru/en), `test_i18n_coverage` stays green.
- [x] 8. Tests: geometry, mask holes, synthetic framed work (perspective + frame), ingest end to end, fallbacks.
- [x] 9. Run the real pilot pair through the real code path and compare with the prototype numbers.
- [x] 10. Full test suite; review section below.

## Rules kept

- Measured beats computed; a hidden element is never measured, only reported as inferred.
- No silent guessing (REQ-003): too few anchors or an ambiguous orientation raises `PhotoError`, the operator places four corners.
- Reference chart is still mandatory (REQ-009); alignment does not change that gate.
- Do not touch unrelated uncommitted work in the tree; no commit unless asked.

## Added after the goal hook (REQ-025, DEC-050, DEC-051)

- [x] 11. Complete capture: nested `SubLayer` settings, `Group` transforms (child XForm first, then the groups above), unsupported shapes counted per layer and noted, image object settings in the layer's settings.
- [x] 12. A layer is not sampled where a later layer engraves over it (burn order = priority, then index).
- [x] 13. Run order (`priority`) is not stored in the recipe of new observations; keys of existing data unchanged (tested against the previous algorithm).
- [x] 14. Whole path of a framed pair checked, reviewed and accepted into observations (synthetic pair with chart).

## Decisions of the operator (2026-10-16) and what was done

- Commit: one commit with the whole tree, no push.
- MarkView: DEC-048..051 accepted, REQ-023..025 approved.
- Old measurement history: removed on request (244 observations, 19 pairs with their stored file copies, 18 capability findings). A verified
  copy of the database and of the files is in `~/.titanium-platform/backup-20261016-142236-before-reset-of-observations`; to restore, stop the
  application and copy `titanium.sqlite` and `files/` back. Device, passport documents, lens, profile, titanium stock, plans, plates and
  research notes were kept. The change is recorded in the audit log.

## Checked against the operator's own files (170 LightBurn files in `Dropbox/Sirius Art`, read only)

- All 170 parse without errors in 26 s. They contain 2370 groups nested up to 7 deep, 86 image layers (grayscale, 3dslice, stucki, jarvis,
  sketch, threshold), 99 image objects, 95 texts (all carry a converted outline) and 45 ellipses; nothing is left unread.
- Group transforms: LightBurn's own thumbnail in the file matches the new reading (circle, letter D and plants of DACUSAN-1; both cards of
  the vCard), while ignoring group transforms shrinks or scatters the drawing.
- `BackupPath` carries the same XForm as its text object (found on real data; the first guess applied it twice and was fixed).
- Image layers: mode, kind (tonal / depth), dpi, dot width and correction, cleanup pass, passes, sub-layer, picture processing; the picture
  is PNG in `Data`, shared by the objects of one file (DEC-052, REQ-026). The tonal profile is validated on synthetic photographs only.

## Pilot pair accepted by the operator (2026-10-16)

Pair 21 (`unbreakable.lbrn2` + `IMG_3281.DNG`, profile JPT MOPA M7 60W) was created in the running application, reviewed and accepted by the
operator: 19 observations, alignment `element anchors`, camera-relative (none model-eligible), run order not in the recipe.

## Photo engraving checked on the operator's own pair (2026-10-16): `Inna - 2.lbrn2` + `IMG_3283.DNG`

- One grayscale image layer: power 5..16.1 %, 300 ns, 60 kHz, 128 mm/s, 1503 dpi. The grey level of the picture sets the power and the power sets
  the oxide colour (the operator's method, confirmed by LightBurn's documentation: Min power for the lightest, Max for the darkest).
- `picturing.py`: the picture's silhouettes (edge maps of the three Lab channels) are matched to the photograph over 8 orientations, refined by
  ECC. Orientation: vertical mirror, margin 2.1 times; hidden by the frame 2.9 / 7.3 / 3.8 / 3.2 mm (left, right, top, bottom); 5.7 s for the check.
- Tonal profile on the real photograph: smooth and monotone, near black and neutral at about 14 % power, brown and most coloured at about 7 %
  (rank correlation with grey: L* 0.64..0.80, a* -0.64, b* 0.50..0.72). DEC-052, DEC-054, REQ-026 and REQ-027 accepted on this evidence.
- The frame of that photograph is brushed metal; the old dark-frame detector does not find it, the step at the inner edge does.

## Answers of the operator (2026-10-16) and what is still open

- **Grey to power: settled (Q-024 answered, DEC-057).** Power = Min + (Max - Min) x (1 - grey) with the layer's own Min and Max; checked against the portrait
  (Min 5, Max 16.1, grayscale). The unverified-sRGB caveat is gone; no wedge plate.
- **Portrait steps: shown on the map by default** (pale, dotted outline, "без привязки к чистому титану"); a checkbox hides them; they stay out of the search until
  "Искать и среди них" (their distances to referenced colours mean nothing).
- **Photographs of plates: the operator sends them one by one** after engraving; nothing to do until then (11 plates show "plate ready").
- **ColorChecker: the operator is thinking about where to get one.** Until a photograph with a chart exists every colour is camera-relative (dashed outline).
- Brightness, contrast and gamma of LightBurn are recorded and listed in the profile, not modelled (they do not reorder grey levels); the dithering of other modes
  is not modelled.

## Experiments as single objects and one general colour map (operator, 2026-10-16): done

Operator decisions: camera-relative colours are expressed against the clean titanium of their own photograph; all laser and lens versions on one map
with a filter; the working-task panel stays, compact, on top. The photograph with its overlay is always shown in an experiment.

- [x] A1-A2. `experiments.py`, `GET /experiments` and `/experiments/{key}`: derived from plates and checks (DEC-055, REQ-028), no schema change.
- [x] A3-A4. One list screen (thumbnail, state, laser, lens, titanium, search, state filter, conclusions beside it); one experiment screen with the
  photograph and its overlay first, then the checks, the measured layers, the plate, the file and the conclusions.
- [x] A5. Old routes keep working and link back; new plates open as experiments.
- [x] B1-B2. `colormap.py`, `GET /colors` and `/colors/search` (DEC-056, REQ-029).
- [x] B3. One map screen: filters, a*b* plane, a palette or Lab input, nearest recipes with settings and where they came from; the model page stays
  reachable (`/colors?profile=`).
- [x] B4. Cleaning layer of a finished work recognised (also for works accepted earlier, from the stored file); linear-light ratio to the clean surface.
- [x] A6/B5. Tests (524 pass); checked in the running application on the operator's pairs.

## Review

### Result (2026-10-16)

- DEC-048, DEC-049, REQ-023, REQ-024 recorded in MarkView (statuses left to the operator).
- `lightburn.py`: exact outlines. Pilot file: 233 of 239 sub-paths closed (the old reader saw 43 of 235 paths); layer areas agree with
  an independent reader to 0.1 %.
- `anchoring.py` (new): window of the frame, 8 orientations with trimmed chamfer cost, pose polishing, per-element anchors, robust
  homography, statuses, bootstrap and a ring hold-out estimate. Pilot pair: 71 anchors, 120 confirmed, 29 partly hidden, median
  outline residual 0.09 mm, orientation margin 0.58 and 0 anchors for the second orientation; 15 s for the whole pair check.
- `ingest.py`: new route before `register_geometry`; frame window limits the measured surface; overlay draws the hidden part in
  magenta; per-layer notes; `_line_metrics` farthest pair via convex hull (was O(N^2): 66 s -> 14 s on the pilot pair).
- UI: method pill, anchor statistics, hidden margins marked approximate, refusal reason; Russian translations added.
- Tests: 486 pass (44 new: geometry, mask holes, anchoring on synthetic framed work, whole pair check and acceptance, farthest pair,
  sub-layers, groups, unsupported shapes, run order, overlap exclusion, key stability).

### Limits to remember

- Only one real pair was available. The reference chart is still missing from `IMG_3281.DNG`, so no observation can be created from it.
- Hidden margins of the plate vary by about 1 mm between runs of different settings; the UI says so. Visible elements are
  registered to about 0.1 mm (median); on synthetic works the worst grid point was 0.14-0.74 mm.
- The frame window is found only for a dark frame with a clear histogram valley; otherwise the old routes and the manual four corners remain.
- Heavily overlapping outlines (painted over) may be refused ("orientation ambiguous"); refusal is the safe outcome.
- See "Still open, and why" above.

## Stream S3: one experiment list, provisional colours, honest search, predicted photo engraving (I-15 part, I-16; 2026-10-18)

- [x] REQ-028: cancelled, superseded and deleted plates (also `plate.status = 'Deleted'` when that column exists) are not experiments;
  the laser page shows the one experiment list filtered by that laser; a finished work offers its LightBurn file on its experiment.
- [x] REQ-020 AC7 / DEC-045: checked, aligned, measured pairs awaiting acceptance are on the colour map as provisional, linked to their
  review; out of the search unless asked for, out of every prediction.
- [x] REQ-029 / DEC-021: one search entry per recipe = settings + laser id + lens id + titanium stock id + kind of measurement
  (chart / against clean titanium / as photographed) + provisional; it counts independent engravings and photographs apart.
- [x] REQ-030: `prediction_store.py` (curve of a mode from tonal profiles and flat fills), `api/routes_prediction.py` (upload, re-render
  at other Min/Max from an in-memory cache, no database), screen "Предпросмотр фотогравировки".

Real check on the accepted Inna pair (pair 22, scratch copy of the live database migrated by the new Store, file copied read-only):
its own LightBurn file through `POST /api/predictions/photo` gives a camera-relative curve "as photographed" (no clean titanium in that
photograph) of 13 points, 6.04..14.37 % power, all from pair 22; 5.49 % of the 1024 x 1024 picture needs a power outside that span
(the 800 px preview alone would say 3.88 %, so the share is counted on the whole picture). The predicted picture binned by grey as the
tonal profile bins the photograph gives back every measured bin within dE 0.01..0.17 (worst at grey 0.906, the lightest bin, whose
lighter half is outside the span). At Min 4 / Max 18 the share outside rises to 32.4 %.


## Vector work colour editor and slow screens (operator, 2026-10-19)

Plan approved 2026-10-19 (`~/.claude/plans/scalable-bubbling-dove.md`). Feature `vector-work-colour-editor` (REQ-043..REQ-049,
DEC-001, DEC-075..DEC-077, issue #28); bug BUG-001 (issue #27). The platform feature was closed before (DEC-079, #26).

- [x] BUG-001 (0.5.2, PR #29, deployed; on 8765: knowledge 6.8 s → 0.12 s, 16 list thumbnails 0.36 s, experiment picture 4 ms): knowledge list once per list (6.8 s on 343 entries); on-disk render cache for photographs and overlays (0.6-3.3 s
  per picture, RAW decoded on every request); 480 px list thumbnails; ETag/304; `warm-cache` command. Release 0.5.2.
- [x] REQ-043 / DEC-001: every source colour coloured from the start, outside-tolerance flagged, never blocking.
- [x] REQ-044: editor with a large picture, zoom/pan, brush / pipette / select, palette, layers, source colours, totals.
- [x] REQ-045: paint scopes area / source colour / fill of similar neighbours, hover preview equal to the result.
- [x] REQ-046..REQ-048: merge titanium colours, source colours, neighbouring areas into one contour (gapless).
- [x] REQ-049: undo / redo over colouring and document versions.
- [x] Full-copy check (work 22: 28 colours coloured, export allowed; 17/17 experiments, 565/565 map points), release 0.6.0
  (PR #30, tag v0.6.0), backup `titanium-before-0.6.0-20261019-085107.sqlite`, deploy (662 observations), view-only walkthrough of
  work 22 in a MarkView tab (demo work 21 no longer exists): 986 areas, no accept button, export enabled, hover of a source colour
  outlines its 49 areas with the tooltip; nothing sent (undo count unchanged), no console errors.

Integration review (2026-10-19). Backend (`segment.neighbours`, `merge_colours`, `merge_regions`; `vector_job` paint scopes, merges,
undo/redo with versions; `GET /reach`) and UI (`vector-editor.js`) merged on `feat/vector-colour-editor`; `set_region` dropped
in favour of `paint` with the area scope. Full suite 1096 passed. Real data (copy of work 22, 986 regions): 30 chained region
merges + 3 colour merges, coverage 0.0/0.0 after every step, LightBurn round trip 902/902 shapes and 55/55 holes; 38 undos back to
version 1, 38 redos identical. Walkthrough in headless Chrome on a full copy (port 8794, never the operator's browser): 28/28
colours coloured, export enabled, no accept button; hover outlines 1 area / 10 areas of a colour / 63 areas of a fill equal to
`/reach`; paint, Ctrl+Z / Ctrl+Shift+Z, Alt+click pipette, Shift+click selection, merge 986 → 985 areas, layers 9 → 8, colours
28 → 27, wheel zoom, drag pan without painting, original view; 6 undos back to the start; at 820 px the panel goes below the
picture, no page scroll; no console errors.

## BUG-001 slow screens (issue #27, branch fix/BUG-001-slow-screens; 2026-10-19)

- [x] Knowledge list O(N): `knowledge.get()` takes the setup's summaries and the entry's events; `list_for_setup` reads them once.
  Test: the list equals `get()` of each entry; `model.knowledge_summaries` runs once per list.
- [x] `render_cache.py`: `<data dir>/cache/renders/<pair id>/<sha256>.png`, atomic write, damaged or missing file redrawn, LRU limit
  500 MB, removed with the pair. Key = canonical JSON of photo and LightBurn file stamps (path, size, mtime_ns), the stored check, the
  plan's JSON digest, the chart reference (corrected only), `allow_non_raw_photos`, every view parameter and `RENDER_VERSION = 1`.
- [x] `size` (64..5000, longest side) on `photo.png` and `overlay.png`; the experiment list asks `size=480`.
- [x] ETag = key, `Cache-Control: private, max-age=0, must-revalidate`; matching `If-None-Match` -> 304 without drawing.
- [x] `titanium-platform warm-cache --data-dir DIR`: the list thumbnail and the experiment page picture of every check in active use.
- [x] Tests: `tests/test_render_cache.py` (7), `tests/test_knowledge.py` (+1).

### Review (copy of the live data, sqlite backup API + copied files, server on port 8793, GET only)

| Request | 0.5.1 | after |
|---|---|---|
| `GET /api/knowledge?device_id=1&lens_id=2` (343 entries) | 6.53 s | 0.07 s (output byte-identical) |
| experiment list, 16 thumbnails one after another, cold | 11.6 s, 35.9 MB (0.65 s median) | 11.3 s, 4.7 MB (0.62 s median) |
| same, 6 at a time as a browser, cold | ~2.7 s, 35.9 MB | 2.4 s, 4.7 MB |
| same, cached / after `warm-cache` | 11.6 s (no cache) | 0.02 s (1-2 ms each); revalidation 304 in 1 ms |
| experiment page `overlay.png?corrected=true&visibility=lifted` | 3.3-3.4 s every time | 3.3 s once, then 3-4 ms; 304 in 1-2 ms |
| `warm-cache` on the copy | - | 32 pictures (16 checks) in 67 s, 39 MB |

Pictures at the default sizes are byte-identical to 0.5.1. The cache key costs 0.1 ms (photo) and up to 9.6 ms (overlay of the pair with
the largest stored check, 529 kB) per request.

Cold time (cProfile, pair 59): the list thumbnail is 0.55 s, of which the RAW decode is 0.52 s (94 %); `size=480` only removes PNG
encode (33 -> 4 ms) and 87 % of the bytes. A corrected picture is 3.2-3.4 s: 8-bit RAW decode 0.51 s, linear RAW decode 0.52 s, chart
correction 2.0-2.2 s (exposure-normalised render 0.65 s, chart detection 0.18-0.27 s, applying the matrix 0.6 s), PNG encode 0.03 s.
Decode and correction were not changed. So the first opening of a picture stays RAW-bound; `warm-cache` after a deploy (and the cache
itself after the first view) is what makes the screens fast.

Not cached: nothing that is served. The vector overlay is cached too (`transparent=true`); `size` was not added to it.


## Vector work colour editor: verification against the rewritten REQ-049 and the operator's answers (goal 2026-10-19)

Branch `feat/vector-colour-editor-req049`, created from `origin/main` (3aa4e45); local `main` was level with it. Spec read in full:
REQ-043..REQ-049, DEC-001 and DEC-075..DEC-077, plan I-1..I-7, discussion.md; the feature has no questions or findings. I-1..I-7 were built
in 0.6.0 (PR #30, issue #28); REQ-049 was rewritten afterwards with unticked criteria, so this goal audits the code against all of it.

Audit (code read, then the tests that cover each criterion):
- REQ-049 holds in the code: `_here` snapshots colouring, split version, tolerance and filters; `_snapshot` clears redo; `_new_version` numbers
  after every version in the history, redo included; variants carry `version` and `restore` refuses another one with a translated message;
  `resplit` clears undo, redo and variants; `_pin_legacy` reads old undo entries and variants as belonging to the current version.
- Gaps found: (a) no test undoes and redoes a titanium-colour merge, (b) the settings test checks only the settings after redo, not the
  colouring, (c) three places where the wording of a criterion and the code differ. The operator answered (c) on 2026-10-19 (DEC-078..DEC-080).

Plan (I-8, steps in the order they were committed):
- [x] Baseline on the branch before any code change: 1104 passed, 1 failed in 11 min 38 s. The failure, `test_plans.py::test_exported_markers_are_
      detected_and_identifier_decoded_from_the_raster`, is a flake: it passes alone (30 of 30) and fails for about 0.75 % of random experiment
      identifiers (3 of 400; `TCE-AFA45888` every time). Cause: OpenCV's classic `QRCodeDetector` misses those codes; the codes are valid
      (`QRCodeDetectorAruco` reads all of them at 10-30 px/mm) and `photo.read_identifier` falls back to it. The test now uses the product's
      reader, and four missed identifiers are pinned (commit 3367022).
- [x] Spec: DEC-078 (a titanium merge needs two or more selected colours), DEC-079 (painting a source colour includes every area of it again),
      DEC-080 (the merge-areas button only for a connected selection); REQ-045/046/048 criteria refined; plan I-8; discussion.md.
- [x] DEC-078: `_merge_titanium` refuses fewer than two distinct selected colours that the colouring uses; one translated message; tests.
- [x] DEC-079: `_paint` with the scope "source colour" and a colour includes every excluded area of that colour; test; the hover agreed already.
- [x] DEC-080: `GET /api/vector/{id}/neighbours` (segment.neighbours, per split version), the screen disables "Слить в один контур" unless the
      selection is connected and says why; the server still refuses; tests (API, screen in node, fallback when the request fails).
- [x] REQ-049 coverage: undo/redo of a titanium merge in a sequence with the other three kinds; redo after a settings change restores the colouring.
- [x] Criteria of REQ-045/046/048/049 ticked with the test seen (175 passed in the files they touch) and the walkthrough below.
- [x] Walkthrough in a MarkView tab on a full copy of the live data (ports 8794 and 8795, never the operator's 8765): see "Walkthrough".
- [x] Full suite on the finished code: 1114 passed, none skipped (10 min 42 s; 1105 tests of the baseline plus 9 new); wheel 0.6.1 built and
      served by an installed copy (CI's check, run locally); version 0.6.1 (DEC-023, SemVer; pyproject.toml; README note).
- [x] Where the commits go: the operator ruled on 2026-10-19, mid-goal, that commits go straight to `main` with no pull request and no new
      branch until he says otherwise (CLAUDE.md). `main` was fast-forwarded to this branch (7 commits), the local branch deleted, and
      `main` pushed (3aa4e45..dd0aceb). He then said not to wait for CI and to switch it off for now: `gh workflow disable CI` (the run
      of dd0aceb, 39309256823, was still in progress and is left to finish); recorded in CLAUDE.md. Not done, as the goal excludes it:
      build and deploy of 0.6.1 to the operator's app on 8765 (backup of the database, install of the wheel, restart).
- [ ] Issue #28 closed with a comment now that the work is in `main`; a note on #32 that its specification landed and nothing of it is built.

### Walkthrough (2026-10-19; MarkView tabs on a full copy of the live data, branch app on ports 8794 and 8795, the operator's app on 8765 only read)

Copy: `sqlite3 -readonly ... .dump` of `titanium.sqlite` with the absolute file paths rewritten to the copy (0 left pointing at the live
directory), `files/` copied (662 observations as in the live deploy). Work 22 "Imma + Boris": photograph, 28 colours, 986 areas, split
version 2, tolerance 0.05, 10 undo steps.
- Opens with all 28 colours coloured, all beyond the tolerance and flagged "вне допуска" ("Дальше допуска ΔE 0.05: цветов 28, областей 986
  (100.0 % площади). Файл они не блокируют."), no accept button, `export_blocked` null; totals "Слоёв 7 из 29 · время слоёв цвета 3 ч 18 мин ·
  средний ΔE 18.55 · цветов в допуске 0 из 28" (REQ-043, REQ-044).
- DEC-080: `GET /neighbours` answers 200, 42 kB, 26 ms, 986 areas, symmetric. With `r7` selected the merge button is disabled ("...соседние по
  границе"); with `r7` and the distant `r1` it is disabled and says "Слить нельзя: выбранные области не связаны общими границами (касания
  углом недостаточно)"; adding the neighbour `r30` keeps it disabled while `r1` stays; without `r1` it is enabled. A real click merged them:
  version 2 → 3, areas 986 → 985, undo steps 10 → 11, and `/neighbours` for version 3 lists 985 areas without `r30`. The "Отменить" button
  brought version 2 and 986 areas back; Ctrl+Shift+Z redid version 3 (REQ-048, REQ-049).
- REQ-049 numbering (second copy): merge → version 3, merge → version 4, two undos → version 2 with 2 redo steps, a new merge → version 5,
  redo 0 and the redo button disabled.
- DEC-079: source colour № 1 has 21 areas; `r32` and `r50` excluded one by one (grey); with the brush on "Весь исходный цвет" the hover outlined
  all 21 areas; the click left `excluded_regions` empty and painted both with the active colour; one undo brought both exclusions back.
- DEC-078: one ticked layer shows no merge control, two show the target list; the merge took layers 7 → 6 ("Слоёв 6 из 29"); the server
  refused `entries=[A], into=B` and `entries=[A, A]` with 422 "choose two or more titanium colours of the colouring to merge", which the
  screen translates ("Выберите два цвета титана из раскраски или больше, чтобы слить их в один"); the refusals changed nothing.
- No console messages on the scripted tab.

Limits: shift-click and Ctrl+Shift+Z were sent as DOM events with the right flags, because the browser tool's key press sends the literal
key "Control+Shift+Z" with every modifier flag false. During the run someone else operated the first tab (a merge of `r232` and `r165` at
19:04:48, a coarse re-split at 19:05:26, two paints, an automatic recolouring), so the rest ran on a second copy at 8795.


## Splitting algorithms, one section for colours and split, Vector Work third (operator, 2026-10-19; feature vector-detail-and-colour-control)

Asked for twice by the operator ("не вижу ... на третье место, и не вижу, где можно выбрать алгоритмы по разбивке"), then "соедини первое и
второе в одну секцию". REQ-051, DEC-080 (the algorithms), DEC-081 (one section) of that feature; criterion 1 of its overview (menu) ticked.
- [x] Menu: `/vector` third (router.js NAV and ICONS together); test for the new start of the menu and for the unchanged addresses.
- [x] Seam: `segment._slic` was the only place superpixels are made. `ALGORITHMS = ("slic", "seeds")`, `_seeds` beside it (OpenCV SEEDS reads an
      8-bit picture; a crop smaller than two superpixels is one), `segment(..., algorithm=)`, recorded in the document; `vector_job` validates
      it (`the splitting algorithm must be slic or seeds`, translated), keeps it in `split`, writes it into the history, reads a work made
      before as slic; `POST /api/vector` takes `algorithm`, `POST .../split` takes it in the body.
- [x] Screen: the split block (algorithm first, with what each is for, number of colours, detail, smoothing, faces, "Разбить заново", counts;
      the picture for marking important areas folded) is a slot of the colours card "1. Цвета и разбиение"; the file card is "2.". The start
      form has the same select.
- [x] Candidates tried through the real pipeline (job's own settings: 12 colours, medium detail), `scratchpad/algo_eval.py`:

  | picture | algorithm | regions | seconds | mean ΔE | p95 ΔE | gap / overlap |
  |---|---|---|---|---|---|---|
  | portrait (work 22) | SLIC | 323 | 2.42 | 7.35 | 17.4 | 0 / 0 |
  | | SLICO | 344 | 3.19 | 7.48 | 18.2 | 0 / 0 |
  | | MSLIC | 342 | 3.60 | 7.48 | 17.5 | 0 / 0 |
  | | LSC | 280 | 3.21 | 7.64 | 19.5 | 0 / 0 (faces smeared) |
  | | SEEDS | 316 | 1.80 | 7.47 | 17.9 | 0 / 0 |
  | sheet photograph | SLIC / SLICO / MSLIC / LSC / SEEDS | 120 / 105 / 136 / 116 / 104 | 0.93 / 1.17 / 1.40 / 1.17 / 0.77 | 3.93 / 3.96 / 4.01 / 3.76 / 3.79 | 11.4 / 10.3 / 11.8 / 10.2 / 9.8 | 0 / 0 |
  | flat shapes | SLIC / SLICO / MSLIC / LSC / SEEDS | 6 / 6 / 6 / **1** / 6 | | 0.81 / 2.30 / 0.83 / 46.2 / 0.82 | | 0 / 0 |

  Offered: SLIC (default) and SEEDS. Rejected with reasons in DEC-080: LSC (faces smeared, one region on a small picture), SLICO (ragged
  borders on flat shapes, no gain), MSLIC (never better than SLIC). A first reading of thin strokes (absolute darkness threshold, 4 colours)
  said SLIC kept 91 % and SEEDS 48 %; it was an artefact of the threshold. Measured as ink against its own surroundings at 6 colours, over six
  noise and shading settings, SEEDS keeps 87-93 % against SLIC's 83-88 % with a third of the regions: that is what the test and the hint say.
- [x] Real flow, on a copy (port 8796, stopped afterwards): SEEDS chosen in the browser on work 22: split version 5 → 6, 985 → 879 areas, 28
      colours, export unblocked, undo and redo reset, the select and the summary line show SEEDS.
- [x] Full suite on the finished code: 1125 passed, none skipped (10 min 43 s; 1114 before plus 11 new). Release 0.7.0 (SemVer: a new capability):
      wheel built and served by an installed copy (menu order and the merged section in its files), pushed to `main` (9d50df7..7ed6215),
      tag v0.7.0 (v0.6.1 on dd0aceb was tagged earlier).
- [x] Deployed to the operator's app on 8765, as 0.6.1 had been: `titanium-before-0.6.1-20261019T192055Z.sqlite` and
      `titanium-before-0.7.0-20261019T195208Z.sqlite` (integrity ok, 662 observations each), app stopped, wheel installed into
      `~/.titanium-platform-app`, started again detached; GET checks on work 22: `/`, the new scripts, the view (1.6 s on the first request after a
      restart, 0.10 s after), `/neighbours`, `/palette` all 200. Between the two deploys the operator worked in the real app (a medium split
      at 19:27 and a coarse one at 19:30 UTC with faces off, paints, random recolourings): work 22 is now version 4, 335 areas, 12 undo steps,
      and the second backup holds exactly that state.
- [x] View-only look at the real app on 0.7.0 (reloaded tab, nothing sent, server state compared before and after): Vector Work third in the
      menu; "1. Цвета и разбиение" with the algorithm select (SLIC selected, SEEDS), its description, the summary line "Алгоритм SLIC · цветов: 28
      · областей: 335", the folded important areas, then colours, variants and "2. Файл LightBurn".
- Left open on purpose: REQ-050 (AI colouring in a chosen style) is a draft with three questions (Q-005 what the AI receives, Q-006 lightness
  order, Q-007 styles); the rest of vector-detail-and-colour-control (density, eyes, smoothing, Contrast and Artistic, automatic merging of
  same-recipe regions) is not built. CI stays switched off (CLAUDE.md); the run of dd0aceb finished on GitHub on its own.

## 0.8.0 plan: a straight layout, methods that differ, smooth contours, colouring by AI (approved 2026-10-19; steps 1-2 done)
Evidence (portrait of work 22, 28 colours, coarse detail, scratchpad `look*.py` and `look*.png`):
- Layout: toolbar labels at y = 748/723/705/748 (flex-end alignment, hints under some fields only); `h4` margin 20 + stack gap 18.
- Methods: SLIC 290 regions vs SEEDS 267 regions, same patches. Different in kind: tonal grid (275 regions, follows the shading:
  brows, lips, nose highlight; 8 s, to be sped up) and graph/Felzenszwalb (173 regions at scale 150: flat planes and ribbons along
  features, 1.6 s). Felzenszwalb at 500+ collapses a face into one region, so the scale is bounded.
- Smoothing: low-pass sigma 0.15 mm today. Prototype on the same arcs, ends pinned: sigma 0.4 and 0.8 mm give visibly smooth contours with
  uncovered 0.00 % and overlap 0.00 %. The format already carries curves: `lightburn.py` reads `B` primitives and the operator's own
  files use them; `vectorize.py` writes `L` only.
- AI: `research.openai_client()` and `.env.local` exist; the real app runs from the repository directory and finds the key. No new library.
Steps (each ends with tests, a commit to main, and a look at the real screen):
- [x] 1. Layout: fields in a grid aligned at the top, hints in the same row height, checkbox and button on one baseline, no empty bands (cf83634; all inputs at y = 695 on screen).
- [x] 2. Smoothing as a live slider (operator's amendment: "он перерисовывает все заново"): `contour.py` low-passes each shared arc
  (ends pinned, corners kept) and fits cubic Béziers; base arcs stay as traced, curves are derived at read time for `plan["smoothing_mm"]`
  (new works 0.5, older 0, max 2), so the slider resets nothing and is not in undo; preview `C`, LightBurn file `B`; export entry records
  the strength. Tests: `tests/test_contour.py` (30), route/export/slider tests in `tests/test_vector_work.py`.
- [x] 3. Methods (tonal sped up 8.6 s to 3.3 s by merging superpixel colours on at most 20 000 points; planes scale fixed at 150; tests: four different maps, no collapse of a shaded face, cap of the clustering input): "Мозаика" (SLIC, default), "По тонам", "Крупные плоскости" and SEEDS kept (the operator's answer: "те же три и SEEDS"; DEC-082); old works keep their key; a test that the four maps differ.
- [x] 4. AI colouring (REQ-050): `ai_colouring.py`, operation `ai_colour`, permission route; styles + own text + free lightness + photo permission; answer checked (measured, complete, layers, lightness), one retry with the reason; a variant that is never asked again. One real call on the test copy: 32 s, 16 recipes. Tests: `tests/test_ai_colouring.py` (fake client).
- [x] 5. Spec: DEC amendments (DEC-082 result, DEC-083 live slider, DEC-084 result), REQ-050..052 ticked, version 0.8.0 (tag v0.8.0, commit 4b43135).

### Review of 0.8.0 (2026-10-19)
- [x] Full suite once, before the release commit: 1215 passed, none skipped (10 min 43 s). Targeted files only during the steps (operator's
      remark about test time).
- [x] Backup `titanium-before-0.8.0-20261019T210411Z.sqlite` (integrity ok, 662 observations), real app stopped, wheel 0.8.0 installed into
      `~/.titanium-platform-app`, started again from the repository directory (key found); GET checks of work 22 (view 1.5 s on the first
      request, palette, neighbours, split.svg, scripts) all 200.
- [x] View-only look at the real app: four algorithms (SEEDS selected on work 22), all fields of the split on one line, the slider reads "как
      найдены" (work 22 was made before the slider), the "Раскраска с помощью AI" panel is there and its button is enabled (a key is set).
      Nothing was sent to the AI from the real app; the one real call was made on a copy of the data (numbers only).
- Test copy on port 8796 stopped. Old test tabs (8794, 8795, 8796) in the MarkView window are dead and can be closed.
- Known and left as it is: `git add -A` put specification changes into the layout commit cf83634; the history was not rewritten.
- Not built (still in vector-detail-and-colour-control): density and eyes controls, Contrast and Artistic modes, automatic merging of
  same-recipe regions.


## 0.9.0: saved works, copy, one-screen workspace (operator, 2026-10-19, after 0.8.0 went live)

Operator's words: "Векторная работа должна где-то как-то сохраняться. То есть, что мы выбрали, как она выглядит. ... И возможность
переделать. И, пожалуйста, переделай UI намного-намного более удобным, чтобы не надо было вообще скроллить."

Findings: a work is stored (plan row + document file + source image), but the screen has only a creation form, no list, so a work can only be
reached by its address `#/vector?plan=22`; the work page is several screens tall. Work 22 was deleted from the UI at 21:37Z (audit 190).

Answers (AskUserQuestion): restore 22 (yes); list with thumbnails + "Сделать копию" (new work from the same state, the old one stays);
layout "one screen, three columns" (tabs of settings left, big picture centre, layers and variants right); the 500-for-missing-library
message and the README dependency step go into the same release. SemVer: a new capability, so 0.9.0 (not 0.8.1).

- [x] 1. Work 22 restored from `titanium-before-0.8.0-20261019T210411Z.sqlite` (one plan row; fresh backup
      `titanium-before-restore-of-work-22-20261019T221230Z.sqlite` first; audit row `plan_restored`; GET /api/vector/22 -> 200, version 7).
- [x] 2. Backend (done by a fork, tests `tests/test_vector_list.py`, 26): `GET /api/vector` (list with facts), `GET /api/vector/{id}/thumb.png`, `POST /api/vector/{id}/copy`; a missing AI library is
      a message, not a 500, and `ai.missing` tells the screen why the button is off. Tests: `tests/test_vector_list.py`.
- [x] 3. UI (`vector-workspace.js`, `App.tabs` in `dialogs.js`, router workspace mode, CSS; tests `tests/test_vector_workspace_ui.py`): "Мои работы" (cards: thumbnail, name, date, algorithm, colours, layers, AI style; Open, Copy, Delete with confirmation); the work
      screen as one viewport (header with undo/redo and file, tabs Разбиение/Цвета/AI/Файл on the left, picture in the middle, layers and
      variants on the right, only long lists scroll inside their panel). Check on screen at 1421x951 and a smaller window.
- [x] 4. Spec (DEC-085, REQ-053, REQ-054), README (0.9.0 section, dependency step of the deploy recipe), version 0.9.0, tag.
- [ ] 5. Full suite once, backup, wheel, install, import every declared dependency from the app environment, one AI call from it on a copy,
      deploy, look at the real app.

### Measured on screen (copy of the data on 8796, window 1421 x 951, work 22: 28 colours, 16 layers)
- The page does not scroll (document height = window height) on any tab; the tabs Разбиение, Цвета, AI, Варианты, Файл and the editor tabs
  Кисть and Слои need no inner scroll. Only the editor tab "Цвета" (28 source colours, 1661 px in a 746 px panel) scrolls inside its panel.
- List: thumbnail 360 px, one card; "Сделать копию" made work 23 "Imma + Boris (копия)" and opened it, both thumbnails loaded.
- The side menu folds away on the work screen and "Меню" opens it.
- Not changed: works made by the fill, text and line strategies keep their long page (`jobView`); the thumbnails share the geometry memo
  (6 entries) with the editor, so a long list can evict the geometry of the work being edited (recomputed in about 0.5 s).

### Release 0.9.0 (2026-10-19)
- Full suite once: 1246 passed, none skipped (666 s). Commit `fdaa132`, tag `v0.9.0`, pushed to main.
- Backup `titanium-before-0.9.0-20261019T224230Z.sqlite` (integrity ok, plans 6 and 22) taken before the real app was stopped.
- Wheel 0.9.0 installed into `~/.titanium-platform-app` (`--force-reinstall --no-deps`, then `pip install <wheel>`); every declared dependency
  imports from that environment; the real app runs 0.9.0 on 8765 (data `~/.titanium-platform`).
- First feature check from the app environment on the data copy (port 8796, stopped after use): list, copy (201) and an AI colouring call
  ("cubism", 41 s, 18 recipes).
- Real app, view only, 1421 x 951: the list shows work 22 with its thumbnail; the work screen has no page scroll (951 = 951); only the editor
  tab "Цвета" scrolls inside its panel.
- Found while looking: work 22 as restored (from the 21:04Z backup) is the older state: document version 7, SEEDS, 308 regions, 6 layers,
  colouring "Ближе к оригиналу", 1 variant. At deletion it was one step further (document version 8, file `vector-075cbfd7c547.json`, written
  21:35:15Z): re-split "По тонам" (medium, 538 regions, the 4 manual edits kept), photo permission on and off, settings tolerance 0.05 with
  "include as shot", colouring "Случайно" then "Сохранить тональность". The deleted row is still readable in the snapshot
  `titanium-before-restore-of-work-22-20261019T221230Z.sqlite` (freed pages). Nothing was written to the real data for this; the operator decides:
  redo the split and the colouring by hand (two clicks), or have the missing step applied (needs approval).
- Not done: `mcp` library is still missing in the app environment (only `titanium-research-mcp` needs it); the old `tolerance_mm` split field is
  still an API parameter; commit `cf83634` mixes spec changes with the layout (history not rewritten).

# 0.10.0 - rename a work, one screen without scrolling for "Эксперименты" and "Карта цветов" (operator, 2026-10-19)

Requests (verbatim): "Сделай возможность переименовать работу"; "Поменяй UI на 1 screen without scroll for карта цветов и для экспериментов".
Answers to my questions: scope = "Пункты меню и вложенные страницы"; experiments = list on the left, working task and findings on the right;
colour map = filters on the left, the map in the centre, the colour search on the right. Measured before (1421 x 951, copy of the data):
experiments list 3725 px, experiment page 4403 px (plate-only experiment 1295 px), colour map 1473 px, model of one laser and lens 30396 px.

Shared frame (done by me first): `.os`, `.os-head`, `.os-body`, `.os-col`, `.os-col-head`, `.os-scroll` in styles.css (section 15), router leaves the
footer out of an `.os` page; `.workspace` next to it also folds the side menu away; `App.tabs` for tabs; below 1100 px the page stacks and scrolls.

- [x] A. Rename a vector work: `POST /api/vector/{id}/rename` (name only, no history entry, no document version, audit `vector_work_renamed`), pencil
      next to the name on the list card, in the work header and on the long page of other strategies, dialog with the field, tests, REQ-055, DEC-086.
- [x] B. "Эксперименты": list (search + two filters, scrolls inside) | working task over findings; keeps the side menu; `ExperimentCards.list` stays usable on the laser page.
- [x] C. "Карта цветов" (general map): filters | big map with projection switch and lightness range | colour search with its results; `.workspace` (menu folds).
- [x] D. Experiment page (`experiment.js`): one screen, tabs/columns by its content, the overlay photo large.
- [x] E. Model of one laser and lens (`colors.js`) and the knowledge page (`knowledge.js`): one screen, a list of sets, the selected set's plot and tables in panels.
- [ ] F. Integration (me): targeted tests of every touched file, REQ-044 / DEC-080 in the spec (done), README 0.10.0 section, version 0.10.0, full suite once, backup, deploy
      (wheel + dependency imports from the app environment + first check from it on a data copy), look at the real app, report with measured page heights.

### Review 0.10.0 (five parallel forks on disjoint files, then integration)
Measured at 1421 x 951 on a copy of the data (`document.documentElement.scrollHeight == innerHeight` everywhere below; GET only):
- "Эксперименты": 3725 -> 951 px; with `?device=`, with a filter that empties the list: 951. The list scrolls inside its panel (2451 px in 587).
- "Карта цветов": 1473 -> 951 px; default, after a search (12 results), after a click on a point (the chart shrinks 684 -> 458 px, the detail strip
  fits), with 76 or 0 colours: 951. Inside: the results list and the unfolded "Как это считается".
- Experiment page: matrix test 4402 -> 951, finished work 1401 -> 951, a second finished work 951, plate-only 1295 -> 951 (measured on its "Плата" tab
  only before the copy lost those plans). Inside: the "Результат" tab with many layers (1951 px in 750 for 10 layers).
- Colour model of one laser and lens: about 30 396 -> 951 for all five sets and every tab, the unknown lens too; knowledge 1, 120, 343: 951.
  Inside: the model list (343 rows, about 23 900 px in 750) and the long "Варианты" / "Все слои" tabs.

Where the old parts went (experiment page): title, status, tasks, add photo, delete -> header; photo, contour and brightness buttons, legend (now a
fold-out "Что означают линии"), caption -> left column; checks -> tab "Проверки (n)"; alerts, margins, measured layers (cards instead of the 5-column
table, same data), tonal tables and images -> tab "Результат"; parameter matrix -> tab "Матрица" (only if the check has one); plate and links -> tab
"Плата"; LightBurn file and photo-preview link -> tab "Работа"; conclusions -> tab "Выводы (n)".
Colour model: calibrated observations -> first item of the list "Наборы"; their map -> centre; table "Модель цветовых параметров" (343 rows, all 8
values and the links to the knowledge pages) -> right column; each RAW pair -> a list item and the centre; "Что видно", "Цветовые варианты", "Все
измеренные слои" -> tabs; warnings, the note about relative Lab and "принять пару" -> under the map; "Нестабильные наборы" -> under the header.
Knowledge: details and the decision buttons on the left; history and evidence on the right.

Shared edits outside the pages: `App.tabs` skips hidden tabs on the arrow keys (dialogs.js); the router leaves the footer out of `.os` pages;
`mapPlot` got an optional `{fit}`. Old `.exp-*` layout rules of the experiment page were removed (nothing else used them).
Caveats: below 1100 px the pages scroll as before (checked by CSS and tests, not in a narrow browser); the copy of the data has no findings for the
material, so the findings panel was checked on injected markup; the knowledge states "под вопросом", "утверждено", "производство" are covered by
mock tests only. During this work three plans of the shared test copy (22, 23, 24) were deleted from it (not by me, a fork used the shared server
beyond GET; see the correction below); the operator's real data was checked afterwards: plans 6 and 22 intact.
Real work 22 meanwhile: the operator re-split it (SLIC, document version 10) and coloured it with the AI at 22:48 and 22:52 (variants 8), so the
AI colouring works in production and the older state of 21:35 in the snapshot is no longer needed.

### Changes during the integration (operator's messages while the full suite was about to run)
1. Menu (DEC-081): "Когда открываю карту цветов - меню исчезает" -> "Пусть вообще оно будет висеть слева и открывается в попапе" -> "короче пусть везде
   будет так". The folded menu is gone everywhere (also from the vector work screen of 0.9.0): a fixed 56 px rail of icons, the button at its top
   (and "Меню" in the header) opens the names as a popup; a click outside, Esc and a choice close it; below 1000 px only "Меню". The five pages of
   0.10.0 lost the `workspace` class (it only removes the width limit now). Measured at 1421 x 951 after the change: experiments, colour map,
   experiment page, vector list, work 22, devices: scrollHeight = innerHeight = 951, no horizontal overflow; settings 1843 (long, as before).
2. Lost work (DEC-082): "Я удалил эксперимент и удалилась моя работа... Почему?" Cause: the experiments list showed vector works and "Удалить
   эксперимент" deletes the plan, which for an unphotographed work is the work. It happened on the test copy (port 8796, audit 192 `plan_deleted` 22
   at 23:18:33Z); the real data was intact (work 22, version 10, audit up to 191). The explanation I had for the earlier missing plans 22-24 on the
   first copy ("a fork") was wrong: it was the same click path. Fix (operator's choice): a vector work without a photograph is not an
   experiment (list and key), and the plan page of a vector work has no "Удалить тест" button nor, before a photograph, "К эксперименту".
   Tests: `tests/test_vector_work_is_not_an_experiment.py` (5; three fail without the change). Still open: a vector work WITH photographs is an
   experiment, and deleting that experiment deletes its checks and archives the plan (the work leaves the work list; rows and files stay).
   Until 0.10.0 is deployed the real app (0.9.0) still lists work 22 as an experiment: do not use "Удалить эксперимент" on it.

### Release 0.10.0 (done 2026-10-19, commit 771ef04, tag v0.10.0)
- Full suite once at the end: 1312 passed, 0 skipped (11 min 50 s). Targeted runs before it: UI files 80, experiments 21.
- Backup before the deploy: `~/.titanium-platform/backups/titanium-before-0.10.0-20261019T235536Z.sqlite` (integrity ok; plans 6 and 22; audit 191).
- Wheel built with the app environment's pip, installed with `--force-reinstall --no-deps` and then with its dependencies; all ten declared
  dependencies import from `~/.titanium-platform-app` (`scikit-learn` under the name `sklearn`; `mcp` 1.30.0 is installed now).
- First feature check from the app environment on a data copy (port 8798, stopped after): list, rename (version stays 10), blank name 422, the
  experiments list without work 22 (16 entries), `/api/experiments/plan-22` 404, the rail in router.js and styles.css.
- Real app restarted on 8765 from the repo directory: 0.10.0, work 22 (Imma + Boris, v10, 12 layers) intact, audit still 191, integrity ok.
  Viewed read-only at 1421 x 951: vector list, experiments, colour map, an experiment page, work 22: scrollHeight = innerHeight = 951,
  rail 56 px, no horizontal overflow; the plan page of work 22 has no "Удалить тест" and no "К эксперименту".
- Open: the test copy on 8796 (`scratchpad/live-copy-4`) holds the operator's own edits (renamed "Inna + Boris", split 23, SEEDS) and is NOT the real
  app; moving them to the real app needs the operator's word. A vector work WITH photographs is still an experiment (see DEC-082).

## 0.11.0: palette from all plates of the material, and as many layers as colours are set (operator, 2026-10-19/20)
Spec ids: DEC-087/REQ-056 (the fifth mode) are SUPERSEDED by DEC-089/REQ-058; DEC-088/REQ-057 (palette) live in the feature `vector-detail-and-colour-control`.
(Ids are per feature: DEC-080..082 and REQ-044 of the 0.10.0 notes above are in the main feature `titanium-color-engraving-intelligence-platform`.)
Operator, 2026-10-20: "Какая кнопка как можно больше цветов? Не нужна такая кнопка. цветов всегда как можно больше и ограничено количеством в
установках" -> asked what to do with the other modes -> "Разные цвета везде, «Меньше слоёв» убрать". Also: "не нужно запускать все тесты пока я не
попрошу - все локально запускай как можно скорее - я проверю" (full suite NOT run for this release; targeted files only).
- [x] DEC-089/REQ-058: `palette._closest` = one-to-one assignment (scipy `linear_sum_assignment`, tolerance-clipped cost, then time; n > m: every entry
  used once, the rest nearest), `_tonality` = strict rising entries (`_monotone(strict=True)`, `_spread` DP without kept choices), `_random` uses every
  entry when the palette is small; `_pool` keeps the operator's kept entries from the others; `fewer_layers` and `most_colours` removed (API error text,
  buttons, translation); `vector_job._automatic` maps a stored old mode to closest; the old name stays in `MODE`/`MODE_NAME` for saved variants.
- [x] DEC-088/REQ-057: `palette._same_material` (family + grade, case/spacing ignored, no grade = itself) and `palette._across_plates` (a recipe on several
  plates is one entry; group/id of the work's own plate when measured there). Record 1 "Test Plate 1mm": "Garde 2" -> "Grade 5" (PUT
  /api/materials/1 after `.backup` titanium-before-grade5-20261020T001540Z.sqlite).
- [x] Measured on a data copy (port 8797, stopped): work 22 palette 18 -> 505; closest 29 of 29 layers (dE 6.97; before 20 layers / 6.16 with the 505 palette,
  7 / 18.5 with 18), tonality 29 (7.84), random 29; old variant 1 restores (7 layers).
- [x] Tests (targeted, 255 passed): test_palette (51: brute-force optimum for closest and tonality, own entry in every mode, every entry used, kept entries,
  merged plates, grade/family/no grade), test_vector_work (5 layers on the fixture, the other-plate test), test_vector_list, UI label tests.
- [ ] Deploy: backup, wheel, install, first check on a copy, real app (no button; palette count; 29 layers on the work when the mode is pressed). No full suite,
  no push/tag until the operator has looked.
Not done and not asked: widening the palette with colours predicted by the laser model (unmeasured; needs its own decision); AI colouring unchanged.

## 0.12.0: confidence in the colour of a setting (operator goal, 2026-10-20; REQ-045, DEC-083)
Operator: new experiments and pictures give "new colours"; a setting needs a confidence in its value and the more confident colours are preferred: the
same colour repeating under the same settings is more confident, a colour that changes is not and "cannot be taken", a yellow that is redone as dark brown
is replaced by the dark brown; more repeats, more confidence; more differences, less.
Measured on the operator's data first (copy, GET only): 539 recipes on the colour map, 23 repeated, 11 of those disagree by dE 7 to 22.8; palette of work 22 =
505 recipes, 496 engraved once, 9 with a confidence; 14 settings are in the palette twice or thrice because chart / against-clean / as-shot are separate recipes.
- [x] A. `agreement.py` (pure): agreeing group within dE 5, newest wins a tie, confidence k^2/((k+2)n), contradicted; unit tests incl. the yellow -> dark brown case.
- [x] B. Palette (what a vector work chooses from): colour = agreed colour, `agreement`, `caution` (contradicted / superseded by a better basis), `automatic()`
      refuses cautioned entries, `_closest` prefers confident before fast inside the tolerance; error text when nothing is left; tests.
- [x] C. Knowledge model `model.summarize` (agreed colour + agreement-aware confidence, stability still over all) and colour map `search` (distance to the
      agreed colour, confidence, agreement); tests.
- [x] D. Screens (+ the operator's addition of 2026-10-20: the diameter of a circle on the colour map follows the confidence): palette table and picker (confidence, "k of n agree", contradicted / replaced), colour map result, knowledge page; i18n coverage tests.
- [x] E. Real data: before / after counts on the copy (changed colours, contradicted, superseded), a work's colouring before / after.
- [ ] F. Release 0.12.0: targeted tests only (operator: no full suite unless asked), README, version, backup, wheel, install + dependency imports, first check from the
      app environment on a data copy, real app view-only. Commit on main, NOT pushed until the operator has looked (feedback of 2026-10-20).
Not in this step: pooling the three measurement bases of one setting into one estimate (REQ-029 keeps them apart); a screen to set the dE 5 limit.

### Review 0.12.0 (before the deploy)
- New code: `agreement.py` (consensus within dE 5, newest wins a tie, confidence k^2/((k+2)n), contradicted = no strict majority), `colormap.agreed / annotate`,
  `palette._entry / _supersede / automatic / _closest`, `model.summarize / predict_for_lab`, `colormap.search / fastest_first`, `/api/colors` points carry `trust`,
  screens: vector colours (table, picker), colour map (circle radius 3 + 12 * trust, title, legend), knowledge page.
- Tests: `tests/test_agreement.py` (11, pure), `tests/test_setting_confidence.py` (16: palette, supersession, assign, knowledge, search, API points), the DOM test
  of the circle diameter in `tests/test_color_map_one_screen.py`. Old tests that pinned "the mean of all engravings" were changed to agreeing data or to the agreed
  colour (test_palette plate merge, test_model rephotographs, test_findings x3, test_vector_work other plate); the anomaly finding now measures from the agreed colour
  (its statement and Russian translation changed).
- Measured on a copy of the real data (GET only, own port 8799, stopped after): colour map 565 points, 517 engraved once (trust 0.33), 22 with two agreeing (0.5),
  3 with three (0.6), 20 + 3 contradicted; palette of work 22: 505 entries, 3 contradicted, 16 superseded (11 of them as-shot, which automatic modes never took), 9 with a
  confidence; palette 0.10 s, colour map 0.08 s, annotate 8 ms (no slower than before). Recolouring work 22 (closest): 29 layers, no cautioned entry used; without the
  rules the old choice would have used one superseded colour (dE 22.7 from its source), mean dE 14.5 -> 16.3 when it is refused (the price of not taking it).
- Headless Chrome on the copy: circles of the map have r = 7 (517), 9 (23), 5 (20), 10.2 (3), 4.3 (3): the map is dominated by colours engraved once.
- Open / not done: pooling the three measurement bases of one setting into one estimate (the better basis only replaces the worse); no screen sets the dE 5 limit;
  `conversion.eligible` (knowledge-based plans) takes the agreed colour through `summarize` but does not refuse contradicted entries (its stage gate stays).

### 0.12.3: zoom and pan of the colour map (operator, 2026-10-20; REQ-046)
- [x] Wheel (about the cursor), sideways wheel / shift + wheel, drag, double click, buttons + / - / whole map, keys, two-finger pinch; circles keep their screen size;
      the view of a plane survives picking a colour. Pure `zoomView / panView / clampView` tested in node; the DOM test covers wheel, drag, buttons, keys, pick.
- [x] Real headless Chrome on a copy of the data (port 8801, stopped): wheel x2.5, drag, drag that starts on a circle does not pick it, plain click picks it, reset.
- Not checked: a real pinch on a touch screen (REQ-046 criterion 4 stays unticked). Released locally and deployed to 8765; NOT pushed, NOT tagged.

## 0.13.0 plan: the measured colour is the colour on the picture; every LightBurn parameter read and shown; re-measure (operator, 2026-10-20) - NOT APPROVED YET
Operator: the colours listed for check 60 (pair 60, IMG_3327.DNG, work "Inna + Boris 2", plan 22) do not match the photo, "especially the dark ones"; the ColorChecker
must make the shown colour the colour on the picture. Also: Q-pulse "not in file" is a bug, all parameters (passes, fill, angle, TC on/off) matter and their defaults
must be known; experiments must be re-runnable after the colour fix.

### Evidence (own analysis of pair 60, copy of the data, read only; scripts in the scratchpad)
1. The chart fit has no offset (3x3 on linear RGB). The photo is ~3 stops under (gains 8-10), so any additive error (flare, black level) is multiplied by ~10 and lifts the darks:
   black patch L 30.4 (reference 21.7), neutral 3.5: 40.4 (36.1), saturated patches desaturated (orange b 45.8 vs 56.1). Affine fit minimising dE in Lab:
   black L 21.0, leave-one-out mean dE 4.0 (now 6.4), max 8.1 (now 12.9). Layer colours move by 0.7-8.1 dE (C07 8.1, C10 5.0, C05 4.3, C16 3.4, the rest < 3).
2. The plate is specular and brighter than the matte white patch: median corrected linear > 1.0 for C05, C07, C10; 87% of C07's pixels are clipped at 1.0, so L is pushed to
   ~99 and the hue moves (stored L 98.8 a -8.9 b 27.5, unclipped L 107 a -0.5 b 39.7). A matte chart cannot certify L* above its own white.
3. One median per layer is not "the colour of the layer" when its elements differ. C16 (the darkest listed, L 55.2 / a 3.3 / b 5.8) has 20 measurable elements:
   brown 47 / 7 / 12 (31.9 k px, the big rectangle at the top), grey-brown 55-58 (16.5 k, 9.9 k px), grey-blue 69 / -3 / -1 (17.8 k px). The listed colour matches none of them.
   Only 25-91% of a layer's pixels are within dE 10 of its median (C15: 25%).
4. The list has no dark colours: after correction only 2.3% of the plate is below L 45; the darkest listed layers are L 55 (C16), 60 (C14), 63 (C12). C16 is also excluded
   from the model (`model_eligible=0`: no QPulseWidth in its layer), so the darkest measured colour never reaches the colour map or the palette.
5. Sixteen layers represent a picture that has hundreds of distinct areas; the picture's own darks are not among the experiments' settings at all.
6. PIPETTE vs CHART (operator, 2026-10-20: "why not take the colour from the photo like an eyedropper?"). The median of a layer's pixels IS an eyedropper; the question is
   which picture it is taken from. On the camera's own preview (the DNG's embedded JPEG, what Photos / Preview show) the chart reads: white patch L 71.9 (reference 95.8),
   grey ramp 71.9 / 59.2 / 44.3 / 30.3 / 18.6 / 9.5 (reference 95.8 / 80.6 / 65.9 / 51.2 / 36.1 / 21.7), mean chart dE 23.9. So the picture is ~20 L* darker than the chart's
   white says. Layer colours, mean L*: pipette on the preview 61.3, exposure only (one gain x7.3 so that the white patch is white, no matrix) 81.0, current 3x3 79.8,
   affine in Lab 80.7. C16: 36 / 56 / 55 / 53; C01: 66 / 82 / 81 / 83. The "lightening" is the exposure normalisation to the chart's white, NOT the matrix; the matrix only
   changes chroma (mean 9.9 -> 14.1 to fit the chart). Clipped layers differ in hue: C07 pipette a -2 b 30, current a -9 b 28 (L 77 vs 99).
   The open physical question (only the operator can judge it with the plate in hand): does the plate look like the camera picture (darker; then the matte chart overstates
   the lightness of a mirror-like plate) or like the chart-corrected photo (then chart-relative colours are right)?

### Part A: measurement (the operator's main complaint)
- [ ] A1. Chart correction: 3x3 + offset fitted to minimise dE in Lab (fallback to the old fit when fewer than 18 patches are found); store `correction.model` and the
      fit residual with every check so old and new measurements are told apart. Tests: synthetic chart with a known offset recovers it; leave-one-out bound.
- [ ] A2. No per-pixel clipping before a layer's colour is taken; the median is taken in linear light and clamped only for display. A layer where > 20% of the pixels
      exceed the chart white gets `lightness_bound = true` (its L is a lower bound); shown on the card; the model keeps it but does not use L as exact.
- [ ] A3. DECIDE AFTER A1-A2 WITH NUMBERS: layer spread. Options: (a) keep the median and show the spread and the dominant cluster on the card; (b) the dominant
      cluster is the layer colour; (c) every element is its own observation of the same recipe (the agreement rule of DEC-083 then judges repeats; it needs the re-measure of C).
- [ ] A4. Proof on the screen: chart table (reference vs measured per patch, dE), grey ramp, and the layer fills drawn next to the corrected photo, so the operator can judge.

### Part B: parameters and defaults (Q-pulse, TC on/off, passes, fill, angle)
- [ ] B1. One module with the LightBurn defaults (bidirectional, cross-hatch, angle, passes, fill mode, interval ...). "Tag absent" is kept apart from "device default";
      Q-pulse and the four TC timings have NO documented default, so they come from the operator. Found on this Mac (`~/Library/Preferences/LightBurn/prefs.ini`): the
      default layer template holds QPulseWidth 2, LaserOn_TC 1, LaserOff_TC 1, End_TC 1, Polygon_TC 10, JumpSpeed 4000, OverrideGalvoTimings true, bidir false; the device
      "JCZFiber" holds Laser_QPulseWidthEnabled true and no timing values. Needs the operator to read the two layers (cleaning, C16) in LightBurn.
- [ ] B2. Every parameter on the layer card, recipe and colour-map details: direction, angle, cross-hatch, passes, global passes, fill, interval, TC timings + override,
      Q-pulse with its source (file / default / supplied). Replace "Q-Pulse нет в файле".
- [ ] B3. A layer without Q-pulse can be completed by the operator (existing `supplied_settings`), after which C16 becomes model-eligible.

### Part C: re-measure an experiment (after A)
- [ ] C1. Observations are immutable (DB trigger). A re-measure inserts new observations that SUPERSEDE the old ones (link to the replaced row); old rows stay as history;
      every derived view takes the newest per (pair, layer). One button per check, and "re-measure all" with progress and a before / after report (changed colours, dE).

### Not in this plan
Pooling the three measurement bases of one setting; a screen for the dE 5 agreement limit; any change to the cameras or the chart itself.

### Decisions needed from the operator
0. NEW, first: which basis for the colour of a layer: chart-relative (now; comparable between photos) or as the camera picture shows it (pipette), or both numbers on the
   card and the operator picks what the palette and the map use? Decided by what the real plate looks like (see evidence 6).
1. A1 + A2 as written (affine fit in Lab, no clipping, a lightness-bound flag)?
2. A3 option, after the numbers of A1-A2 (recommendation: (a) now, (c) later).
3. B1: the Q-pulse and TC values LightBurn shows for the cleaning layer and C16 of "Inna + Boris 2" (or the device settings).
4. C1: supersede-by-link (recommended), or something else.
5. Order: A, then C, then B (recommended; B does not change existing observations).

### 0.13.x plan after the operator's decisions of 2026-10-20 (DEC-085 pipette; "Q-Pulse default is 200, set it in the parameters")
Decided by the operator: the colour of a layer is taken like an eyedropper from the picture (DEC-085); the default Q-pulse is 200 ns and is set in the parameters.
Evidence added: the camera's own exposure is not steady - the chart white reads L 72..91 over 14 photographs (median 82.5), so one recipe photographed twice can differ by
several L*; the same-recipe agreement (dE 5) will count some repeats as differing. Recorded in DEC-085; the operator is told, not asked.
- [-] 0.13.0 P1-P5 (eyedropper on the camera's embedded preview, `measurement_basis`, `is_standard`): DROPPED 2026-10-20 after the measurement: the preview reads the
      chart 20 L* darker than the real chart and changes with the exposure (DEC-085 rejected). Replaced by DEC-087 (look-up among the 24 squares), below.
- [x] 0.13.0 (released, deployed to 8765, not pushed) Default Q-pulse width as a parameter of the laser (passport `default_pulse_width_ns`, 200 for the JPT M7 template and for the operator's laser): a layer whose
      file has no QPulseWidth takes it with the provenance "laser default"; shown as such; DEC about the rule "nothing is filled in automatically" (REQ-015/016).
- [ ] 0.13.2 Re-measure an experiment (`create_alignment_revision` + check + accept; one button, and all experiments with a before / after report on a COPY first).

### 0.13.1: the colour is found among the 24 squares; the screens show the picture the numbers come from (operator, 2026-10-20; DEC-087, proposed)
Operator: "work in the other direction: you know the 24 squares; take the colour with an eyedropper and find it among the squares; why lighten or darken at all?"
- [x] Measured on 15 charted photographs (leave one square out): global matrix 4.5 dE (dark squares 5.0, worst 12.9); matrix + offset 3.8; radial basis 4.5-4.7;
      look-up of the 4 nearest squares on an affine base 3.6 (dark 3.1, worst 8.8). Check 60: grey ramp 95.8/80.6/66.1/51.3/36.5/21.7 against 95.8/80.6/65.9/51.2/36.1/21.7.
- [x] `photo.fit_lookup` (affine base in Lab + nearest-squares local correction, honest leave-one-out residual), picture map through a 41-node LUT in threads, `CALIBRATION`
      switch ("lookup" default, "matrix" kept); `tests/test_lookup_correction.py` (8 tests).
- [x] Screens: the check screen opens on the corrected picture when the chart is usable and does not lift it; the experiment screen lifts only the uncorrected RAW unless the
      operator chooses; the cache pre-warm follows the same rule.
- Finding: the layer colours of check 60 change little (mean dE 2.6, mean L 79.8 -> 80.1): the "lightening" was the exposure of the white square and, on screen, the gamma lift
  of 0.58 on top of the corrected picture / the dark uncorrected default view. Specular layers C05, C07, C10 still saturate (L 98-99).
- [ ] Open: layers brighter than the white square (flag "above the chart's white"); pixels of a layer covered by an earlier engraving (the pink / green areas missing from the list);
      IMG_Lion chart read wrongly (grey ramp not monotonic, residual 38) - must be refused with a clear message; all LightBurn parameters shown with defaults (TC timings unknown);
      0.13.2 re-measure (rehearse on a copy, before / after report, ask before applying to the real data).

### 0.13.2: re-measure (operator, 2026-10-20: "redo all experiments with the new calculations"; DEC-088, proposed)
- [x] `ingest.remeasure_pair` (revision -> check -> review -> accept; kept untouched unless the colour basis is the same, no problems and no layer less),
      `POST /api/pairs/{id}/remeasure`, buttons on the experiment and analysis screens, `tests/test_remeasure.py` (6).
- [x] Rehearsal on a COPY of the real data (paths rewritten to the copy: the real DB holds absolute file paths and accepting a revision unlinks the old pair's files).
- [x] Applied to the real data in 0.13.3 (after the pulse-width rule was settled, so each pair was measured once more only): see 0.13.3.
- Trap found: the database stores absolute file paths, so a plain copy of the DB would make `delete_pair` unlink the REAL files. Rewrite the paths in any copy first.

### 0.13.3: any Q-Pulse in the laser's range (operator, 2026-10-20: "who said 300 is not supported? I entered it and it works"; DEC-089, accepted)
- [x] Asked: any width 1-500 ns with an interpolated cut-off (chosen) / add the values to the table / any width without power loss.
- [x] `devices.pulse_range`, `cutoff_for` (log-log interpolation; CW neighbour -> the other neighbour), `require_selectable` = range, operating point says "interpolated"; default pulse width in range.
- [x] Tests moved from off-step values (7, 5, 210) to out-of-range ones (600); `tests/test_pulse_width_range.py`.
- [x] Deployed 0.13.3 (backup titanium-before-0.13.3-*.sqlite) and re-measured ALL 17 accepted pairs on the real data through the app (new pairs 61-77; old ones Deleted, rows kept):
      539 layers, mean dE 1.98 (chart pairs 1.4; the 4 camera-relative pairs 6.7: they were measured by an older pipeline); model-eligible 353 -> 474 of 540 (the rest: 65 camera-relative layers
      by design, 1 cleaning witness); no active observation without a pulse width; colour map 0.14 s warm.

### 0.14.0: "work on the errors" - close the loop promise -> engraved result -> conclusion -> correction (operator, 2026-10-20; DEC-090 proposed, REQ-047 draft)
Operator's goal: what the screen promises must equal what is engraved. After each LightBurn file the operator reports the result (photo); the system compares, concludes about
the work and the existing works, and may swap colours / change parameters / find the problems. Decisions of the operator: the conclusion lives inside the work plus a mark in the
list of works; the system proposes replacements, the operator applies them.

Found in code and real data: the palette is re-read on every view (a new measurement already changes the preview); a vector work kept the preview colour (`lab`) but `prediction` was None, so
its pair report compared nothing; an export kept only its number of layers; the engraved file need not be the exported one (pair 77 matches 0 of 16 layers of work 22 by settings).

- [x] A. An export keeps what every layer promised (`exports[n].promised`: settings, colour, basis, area, regions); older exports are reconstructed while the colouring is unchanged ("approximate").
- [x] B. Engraved layers matched to the promise by settings (0.5 %), greedy by closeness, each layer once; unmatched layers listed on both sides.
- [x] C. Review per layer (promised / got, dE, dL, dC, dh, beyond, causes from the measurements, systematic shift, poor chart), stored in the work (`reviews`, one per engraving), Result tab with
      two pictures (promised / measured colours), mark in the list, block in the pair report, message on acceptance.
- [x] D. Drift of every work of the laser and lens against the last file's promise (recipes no longer used are settled; never-exported works are not marked), counts kept for the list
      (`attention`), replacement proposals (closest measured colour, >= 1 dE nearer), applied by the operator as ordinary edits.
- [~] E. Causes: only what the measurements show (highlight above the chart white, different basis, no chart, poor chart, one shift of most layers). Not done: recipe measured once / unstable,
      below the cut-off, covered by another layer (order).
- [ ] F. Parameter changes (power/speed) from measured neighbours, or send the colour to the Experiment Designer as a target. Not done.
- Assumptions to confirm: visible difference 5 dE (the chart's own error is about 3.6), replacement gain 1 dE, poor chart 7 dE, systematic shift 3 L* on 75 % of layers.
- Tests: tests/test_work_review.py (23), tests/test_work_review_ui.py (4); the vector UI tests list the new tab and script.

### 0.14.1: "Загрузить фото для этой работы" (operator, 2026-10-20; REQ-048 draft)
Operator asked for the link after learning that a photograph links to a work only through the TCE1 identifier in the file's notes (pair 78 "Inna + Boris 2" carries the identifier of work 22 but its layers were edited, so 0 of 16 matched).
- [x] Link on the Result tab (empty and filled state) -> `/ingest?plan=<id>&material=<id>`; the form takes laser, lens, titanium from the work, names it, links back.
- [x] Pair page names the linked work (`plan_name` on the pair).
- [x] Check warns when the file's identifier names another work than the chosen one (the file's identifier wins; a file without one falls back to the chosen work).
- [ ] Not done: the chosen work forcing the link when the file names another one (would hide a wrong file); a link on the "Файл" tab next to the saved files.
- Tests: test_work_review_ui.py (3 new), test_plan_ingest.py (1 new); targeted run in pytest_0141.log. Full suite not run.

### 0.15.0: the colour map says how far a colour is trusted and where it comes from (operator, 2026-10-20: "filter < 1 diameter", "show the confidence when I pick colours", "show where we know this colour from"; REQ-049 draft, DEC-091 proposed)
Operator's words, all on the colour map screen. "Diameter" is the circle of a colour (REQ-045, DEC-084): radius 4 for an engraving never repeated, x1.5 for each repeat that gave the same colour,
/1.5 for each that gave another, 2..14. Agreed with the operator: "1 diameter" is the circle of one unrepeated engraving; a colour whose circle is smaller than that (more engravings differ than
agree: `agreeing - 1 - differing < 0`) is "doubtful" and can be filtered out.
- [x] A. Server: `agreement.doubtful(found)`; `colormap.annotate` marks each point `doubtful`; `/colors` and `/colors/search` take `hide_doubtful` and report `counts.doubtful`.
- [x] B. Server: `sources` of a recipe = its independent engravings (experiment, pairs, photographs, date, colour, dE from the agreed colour, whether it agrees, measurement basis);
      on every search match, and on `/colors` as `recipes[group]` for recipes engraved more than once.
- [x] C. UI: filter "hide colours we doubt" (remembered with the other filters, counted in the head); the picked colour shows its confidence (the circle as on the map, the number, "N of M agree")
      and "Where we know this colour from" (every engraving, who agrees, links to the experiment and the analysis); the search results show the same.
- [x] D. Tests: tests/test_colormap.py (annotate / filter / sources / API), tests/test_color_map_one_screen.py (UI in node). Targeted only; the full suite is not run.
- [x] E. REQ-049 (draft) and DEC-091 (proposed) through the markview tools, README 0.15.0, version 0.15.0; deployed to 8765 after the commit (backup, wheel, restart); nothing pushed or tagged.
- [x] F. Done as 0.15.1 (below).
- Not touched by me: pair 101 (the operator deleted it and uploaded the photograph again as pair 102 with the material "Small Plate"; 102 is "Ready to accept", not accepted).

### 0.15.1: the check does not measure layers the photograph cannot show where the file puts them (operator, 2026-10-20: "Не находит", screenshot; agreed "Согласен - вперед"; REQ-050 draft, DEC-092 proposed)
The file engraved from work 22 had the picture resized to 100 x 100 mm and moved; layers C18 and C28 are hidden in LightBurn, so its tools skipped them and they stayed at the export's 150 x 143 mm
places (outlines on the ruler and the chart; 16 of 29 uncertain elements; rows C18 dE 23.7 and C28 46.0 meaningless). C28 also has its output switched off.
- [x] A. `lightburn.Layer.hidden` and `.output_off` (from the `hide` and `doOutput` settings of the file).
- [x] B. `left_behind.py` (pure): per-axis scale, offset and mirror shared by the layers of the engraved and exported files; a layer is left behind when it sits at the export's place and not at the moved place.
- [x] C. `ingest._leave_out_layers` called by `check_pair`: flags `left_out`, adds a note and a warning, drops the shapes of those layers so alignment, coverage and measurement skip them; the overlay skips them.
- [x] D. Russian translations of the warnings and notes (`i18n-rest.js`); `test_i18n_coverage` green.
- [x] E. tests/test_left_behind.py (11 tests; a mutation of the detector fails 4 of them); targeted run of 459 tests green (`pytest_0150b.log`). Full suite not run.
- [x] F. Checked on a COPY of the real data: pair 102 -> C18 left behind, C28 output off, 28 of 30 layers measured, alignment valid (256 of 269 elements found, 2.6 px), the other layers move by at most 0.8 dE.
- [x] G. REQ-050 (draft) and DEC-092 (proposed) through the markview tools, README 0.15.1, version 0.15.1; deployed to 8765 (backup, wheel, restart); nothing pushed or tagged.
- Not decided: pair 102 (accept or not): 27 layers beyond tolerance in the earlier review of the same photograph; the operator chooses.

### 0.16.0: replace a colour of a work with a chosen one, and see where every colour comes from (operator, 2026-10-20: "I cannot change colours simply", "I want to see where the colour comes from: tests or an existing work", "replace it with a more stable colour", "I do not understand exclude"; plan agreed with "да делай"; REQ-051 draft, DEC-093 proposed)
Today the editor's "Цвета" tab (source colours of the picture, each with the titanium colour it will be engraved in) offers only a merge checkbox and "Исключить"; the picker with "Изменить" exists only in the table on the work page. "Исключить" removes
every area of that colour from the file (they are not engraved), which reads like a missing colour. The picker shows the basis, the number of engravings and photographs, dE and the confidence, but not which test or work the colour was measured in.
- [x] A. Server: every point of the colour map says what its engraving was (`origin`: test = calibration plate, capability test or parameter matrix; work = everything else; `work_id` of a vector work);
      `colormap.sources_of` carries it; palette entries carry `sources` and `doubtful` (so the picker, the editor and the work's own colours show where a colour comes from).
- [x] B. UI shared: `App.sourcesBlock` (the "where we know this colour from" block of the colour map moved to app.js, now with the kind of each source and a work link) and `App.originText`; the colour map uses it.
- [x] C. UI picker (vector-colours.js `pick`): "Откуда этот цвет" for the chosen colour, stability line (confirmed by repetition / one engraving / doubtful), sorting (closest | most stable | fastest), filter "only repeated colours",
      and "Стабильнее и похоже на этот цвет": colours more stable than the current one, nearest to the current one first.
- [x] D. UI editor "Цвета" tab: a row has "Заменить" (the same picker, `set_colour`), "Автоматически" when set by hand, where the colour comes from in one line; "Исключить" becomes "Не гравировать" with a hint of what happens, an excluded row says "не гравируется"; a short explanation of the tab.
      The table on the work page uses the same words. The brush's "active colour" shows where the colour comes from.
- [x] E. Tests (targeted), README 0.16.0, version 0.16.0, REQ-051 and DEC-093 through the markview tools, deploy to 8765 after the commit; nothing pushed or tagged; full suite not run.

Review (0.16.0, 2026-10-20): the colours tab replaces a colour from the editor and says where each colour comes from and how stable it is (REQ-051, DEC-093); the LightBurn file of a vector work
carries MirrorY and writes both handles of every Bezier edge (REQ-052, DEC-094). Targeted run of 695 tests passed (editor and colour-map UI, palette, colormap, vector work, vectorize, ingest,
left behind, i18n, UI files, and neighbours); the full suite was not run. Deployed to 8765 before the run finished, at the operator's request (backup titanium-before-0.16.0-20261020T104412Z).
Warm timings: /api/colors 0.16 s, /api/vector/22 0.17-0.21 s, palette 0.19 s. Not pushed or tagged. The effect of MirrorY in the operator's LightBurn is confirmed only by a new export.

### 0.17.0 plan: photo engraving understood, and works that mix vector layers with photo engraving (operator goal, 2026-10-21) - written before the build
Operator's words: some works are "a mix: part vector, part photo engraving, one layer is the photo engraving"; (1) understand photo engraving: the kinds, their parameters, their
results, and a prediction of how an engraving will look at given settings ("a big piece"); (2) understand in experiments that part of a picture is photo engraving and part is fill.

#### Evidence (own analysis, read only, scripts in the scratchpad; the real app on 8765 only read, new pairs only on a COPY of the data)
- The operator's art folder (/Volumes/Storage0/Art/Laser, 27 files with a LightBurn project) holds 8 mixed works and 3 image-only ones. Image modes in use: grayscale (1500 dpi, Min 1-3 / Max 27-30 %,
  100-150 mm/s, 60 kHz, 300 ns; one at 2048 dpi 0-15 %), jarvis (2540 dpi, dot width 0.01 mm with dot correction, 25 %, 150 mm/s; 1100 dpi in Downloads/deploma.lbrn2), sketch (1100 dpi). The earlier
  survey (DEC-052) also names 3dslice, stucki and threshold. A mixed work = a cleaning rectangle + 7..20 colour fills (Scan) + ONE Image layer burned last (priority highest).
- The Image layer's bitmap covers a rectangle (Joker 152 x 152 mm) but only 70 % of its pixels are opaque: the transparent part is where the vector fills are. In deploma.lbrn2 three small
  sketch/jarvis bitmaps (60-85 % white) lie over the fills; in Sleeping Girl the 16 fills have output OFF and only the photo burns.
- DEFECT, measured on the operator's real works (check on a COPY, finished-work photographs without a chart): `_covered_by_later_layers` treats the whole bitmap rectangle as "engraved again by a later
  layer", so ALL 7 fills of the Joker and ALL 6 fills of "girl art deco" come out "100 % engraved again ... not measured"; only the photo layer gets one median colour. Geometry (first reading, superseded by the check in the Review below) said the fills lie
  under 0-3 % opaque pixels of the picture; that holds for the Joker, not for girl art deco, whose picture is a jarvis halftone over all the fills.
- Real photo-engraving pairs (93 Girl on a bike, 88 Motorcycle, 85 Inna-2; all grayscale) are aligned by the picture and give a tonal profile; the existing prediction (grayscale only) reproduces its own
  pair. Leave-one-pair-out on the two pairs that share one mode (same plate stock, speed 150, 60 kHz, 300 ns, 0.0169): power >= 16 % (dark tones) 1.2-2.9 dE; power < 15 % (light tones) 10-16 dE
  (L* 65-67 in one photograph, 75-82 in the other). It is NOT optical blur (sigma 0-0.8 mm tried), NOT a smooth illumination field (polynomial up to degree 3), NOT heat from the neighbourhood (mean grey
  over 0.5-16 mm): the cross-picture error stays 7-8 L* rms whatever is added. So two engravings at the same settings differ in light tones, and a prediction must show that spread instead of one line.
- The colours of a photo engraving are iridescent (gold, orange, violet, blue by power), not only a lightness ramp: the prediction already carries Lab per power; the descriptor "tonal" is a colour path.
- Nothing classifies photo against fill from the photograph; nothing writes `CutSetting_Img`; no plate engraves a grey ramp per mode (explore report, 2026-10-21).

#### Order (what the operator named first, and what blocks what)
- [x] A. Kinds of photo engraving, one catalogue (`photo_modes.py`, pure): per mode (grayscale, threshold, ordered, atkinson, dither, stucki, jarvis, newsprint, halftone, sketch, passthrough, 3dslice)
      its family, what the grey level controls (power / dot density / depth), the settings that matter, whether a pixel fires (transparent and, in binary modes, white never fire), what the platform can
      predict. `image_summary` carries it; the labels on the screens come from it (today `ordered` and `passthrough` are missing from the label maps).
- [x] B. Mixed works in experiments (blocks every real mixed work):
  - [x] B1. The area an Image layer really engraves (`fired` mask in mm: opaque pixels, mode rule) replaces the bitmap rectangle in `_covered_by_later_layers`; the vector fills under the transparent part
        are measured again. Fills under a pixel that fires stay "engraved again". Tested on synthetic files AND on Joker / girl art deco (before: 0 of 7 / 0 of 6 fills measured).
  - [x] B2. The composition of a file, pure and shown with every check: per layer its kind (cleaning, fill, line, photo tonal, photo depth), area, the share that shows in the end (not covered), the share
        of the picture area that is photo, fill, both-with-holes, nothing; the Image layer's own opaque share. On the review screen and the experiment screen.
  - [x] B3. Tonal profile on the visible opaque part only (transparent pixels excluded; regression on Girl on a bike: identical bins, rho 0.898). NOT built: one profile per bitmap object - every real Image layer
        has exactly one picture object (every real Image layer examined in this work), so there is nothing to split. Dithered modes give grey -> colour bins too: that is C2.
  - [x] B4. (decided against, with the numbers) What the photograph says about the kind: the spread (robust, L*) of each layer's visible area is reported next to the median; a fill that varies like a picture or a photo layer that is flat is named,
        with a threshold taken from the real works' numbers, not invented.
        Result: the spread is reported as information only. On the Joker a flat fill (fill 6, L-spread 6.4) varies MORE than the photo layer (5.5), so no threshold separates flat from tonal; a verdict
        would have been invented. The kind comes from the file (layer type and mode), which is exact; the photograph only says how stable a colour is.
- [x] C. Prediction of a photo engraving (C3 stays open)
  - [x] C1. A curve point keeps how far independent engravings disagree at that power (the 10-16 dE of the evidence above); the preview names the share of the picture in uncertain powers.
  - [x] C2. Dithered modes: the colour of a grey level is read from tonal profiles measured in the same mode and settings (no dither model needed); refused with the reason only when nothing was measured.
  - [ ] C3. Open until C1-C2 are measured on real data: a dot simulation for a mode never photographed (assumed, flagged); a photo-mode test plate (a grey ramp per mode) needs the Image-layer writer, so
        it needs the operator's yes (the file must open in LightBurn; the three real files are the reference for the structure).
- Not decided, needs the operator: (1) pure white in grayscale mode - does Min power fire on it? (the real photographs show no step at pure white; settled by a ramp plate, C3); (2) path shapes
  that sit on an Image layer (Lana Portrait: 12 outlines on C17) - does LightBurn engrave them? They are kept as they are and named in the composition.
- Tests while building: only the files touched; the full suite once before the release; deploy after a backup; "reload the page (Cmd+R)" in the report.

#### Review of 0.17.0
- Built: `photo_modes.py` (catalogue, strike rule), `composition.py` (the file by layers, shares fill / photo / both), the strike mask replacing the bitmap rectangle in the "engraved again" test, the
  tonal profile without transparent pixels, `photo.sample_spread`, the spread between independent engravings on every curve point and in the preview, transparent pixels blank in the preview,
  prediction of the dot modes from the tonal profiles of the same mode, the Russian table `ui/photo-modes.js` with a test that compares it with the catalogue, the composition card and the layer notes.
- On the operator's real works (copy of the data, read only): Joker 0 of 7 fills measured -> 7 of 7 (Lab in the report); the Image layer's colour L 48 -> 84 once the figure left its sample; girl art deco
  stays unmeasured and now says why (jarvis picture over all fills, dot density 48 %). Girl on a bike, re-checked as a new pair: identical tonal bins.
- Needs the operator's decision (not changed): (1) in one curve, flat-fill points and photo tonal points of the same mode disagree up to 39 dE (the Power x Speed plate against Girl and Motorcycle) - should
  flat fills stay in a photo-mode curve at all? (2) the assumptions: a plain shape on an Image layer strikes nothing; threshold cuts at mid grey; white is struck at Min in grayscale (documentation and
  forums, not measured); (3) a photo-mode test plate (a grey ramp per mode) needs an Image-layer LightBurn writer (C3).
- No real photograph pair in a dot mode exists in the database: that prediction is tested on synthetic works only and says so.
- Tests: full suite, 1494 passed, none skipped, serial 14 min 15 s (`.venv/bin/python -m pytest -q -rs`). `pytest-xdist` 3.8.0 was installed into `.venv` with the operator's approval (2026-10-21) and
  declared in the `dev` extra of `pyproject.toml`; the same 1494 pass on 12 workers in 2 min 32 s (`-n 12`). It is a development tool only: the app environment on 8765 does not get it.
- New tests: `test_photo_modes.py` (12: catalogue, strike rule, orientation, UI table equals catalogue), `test_mixed_work.py` (8), `test_dot_modes.py` (14: spread, transparency, dot-mode prediction,
  `sample_spread`). Changed on purpose: the dither-refusal tests (REQ-030 refused every dot mode, DEC-096 predicts seven of them), the mode record in the API test, the node harness of the experiment screen
  (it must load `photo-modes.js` and `composition.js`).

## 0.17.1: the work is found by any picture of the file and the ruler (REQ-055, DEC-097)

Operator, 2026-10-21 (voice-typed): pair 105 (`deploma.lbrn2` + `IMG_3307.DNG`): "Не смог найти картинку"; "исправь, чтобы находила диплом"; "достаточно найти один из слоев, все остальные ты можешь рассчитать ...
Важно, какой слой ты найдешь. НЕ важно"; "ты можешь ориентироваться на линейку ... масштабы, один из углов, плюс ... направление по линейке"; "он может определять тебе, в какой области искать любой из секторов
заливок"; "Это не просто линейка, а уголок".

- [x] A. Root cause, on the real files (copy of the pair through GET, scratch Store, nothing mutated): the check dropped every output-off layer before the alignment; the only active layer is a 25 x 23 mm seal
      (symmetric, ambiguous alone, picture route refuses), the outline route has no outlines, so the operator's four corners were fitted to the seal's bounding box (anisotropic 0.0104 / 0.0080 mm/px).
      Not a regression of 0.17.0 (REQ-050 / 0.15.1).
- [x] B. Evidence before design: the other layers ARE on the plate (template match of their pictures at 19.6 px/mm: eagle 0.49, seal 0.57, signatures 0.69 in one orientation, vertical flip), and the photograph shows
      a measuring angle (two rulers) with the plate in its inner corner.
- [x] C. `ruler.py`: scale from the 1 mm tick spectrum with its 5 and 10 mm ticks (chains of windows along a narrow strip, leakage and half-period handling), the inner corner and side of an angle.
- [x] D. `picturing.locate`: every picture of every layer (output-off included, `Layer.placed`), eight orientations, scale +-5 %, agreement of the pictures on the file's origin, ECC twice, one homography; the
      side of the angle first, the whole photograph if nothing is found there.
- [x] E. `ingest._locate_by_ruler` after the outline and largest-picture routes; the scale as read, doubled, halved; warnings; UI label; Russian translations.
- [ ] F. Not built, flagged: the ruler's direction as a rotation prior (strip edges were not stable on the real photograph; the search tolerates about 1.5 degrees instead); fill layers as templates (Q-029);
      the manual corners fitted to all layers (Q-028).
- [x] G. Tests, docs, release.

#### Review of 0.17.1
- Pair 105 in a scratch Store, full `check_pair`: method "picture at ruler scale", C05 measured Lab [60.3, 0.2, 6.5] at the seal (before: [72.6, 1.7, 13.8] at the wrong place); the overlay frame sits on the seal;
  the plate's lower-left corner of the cleaning rectangle falls within about 1.5 mm of the angle's inner corner (independent check). Ruler 19.64 px/mm against 19.67 fitted from the pictures; the three pictures
  agree within 0.13 mm; correlation after refinement 0.68 / 0.84 / 0.88.
- Real data, GET only (19 other pairs): the ruler is found on 15, absent (none reported) on 4. Where an accepted alignment gives the scale it agrees within 0.2-3.2 % (pairs 88, 90-93, 102); pairs 103 / 104 read
  half (the doubled scale is tried), pair 89 has the plate in a frame above the ruler's plane (1.5 times: not searched). Pairs 88 and 93 (colour portraits, aligned by the older route): `locate` refuses (correlation
  at the true pose 0.09 or below), so it cannot override them. No pair other than 105 has a picture the older routes miss; `locate` is validated on one real work and on synthetic ones, and says so.
- Needs the operator: (1) check pair 105 again with the automatic alignment (its stored check keeps the wrong frame); (2) Q-028 and Q-029.
- Cost: about 2 s for the ruler and 7-11 s for the search, only when every other automatic route has failed.
- Tests: full suite, 1518 passed, none skipped, 2 min 42 s on 12 workers (`-n 12`). New: `test_ruler.py` (7), `test_locate.py` (12), `test_ruler_alignment.py` (5, through `check_pair`), two assertions in `test_left_behind.py`;
  `tests/synth.py` gained a work of three pictures beside a measuring angle (`pictures_work`, `draw_angle`).

## 0.17.2: every layer the alignment placed is drawn; the version is in the header (REQ-055, REQ-056)

Operator, 2026-10-21, after 0.17.1 on the real pair 105 (re-checked, method "picture at ruler scale"): "В новой версии нашел только 1 картинку" (screenshot: one magenta frame on the seal; the eagle, the signatures
and every fill have none). Earlier: "Мне непонятно почему я не вижу версию апликации в header?" - answered (the version is only at `GET /api/version`, DEC-023), operator: "с версией согласен".

- [x] A. Root cause (confirmed on the stored check, GET only): the check found three pictures (C04 0.68, C05 0.84, C06 0.88) but `_draw_overlay` skips every layer flagged `left_out` (REQ-050), and the layers whose output is
      off carry that flag. Only C05, the one layer that is on, is drawn.
- [x] B. The overlay draws the layers of an alignment that was found by their pictures (`alignment.located`): output-off layers are drawn where the same transform puts them, in a colour of their own, not measured.
      Layers left behind stay undrawn (REQ-050). Without `located` nothing changes.
- [x] C. The note of a layer whose picture was found says so ("its picture is on the plate"), not "was not engraved": the photograph shows it was.
- [x] D. Judge the overlay on the real pair 105 by numbers and by looking: the outlines of the fills (text, cleaning rectangle) must lie on the engraved text.
- [x] E. The header shows `v<version>` next to the name (from `GET /api/version`, one request; nothing shown if it fails); Russian tooltip; UI test.
- [x] F. Tests, MarkView (REQ-056 for B-C and the version, DEC-098), README 0.17.2, lessons, version bump, release, deploy; tell the operator to reload (Cmd+R) and that the stored check needs no re-run (the overlay is redrawn from it).

#### Review of 0.17.2
- Real pair 105 (the stored check fetched with GET, the cached files, the working-tree code): the overlay now outlines all six layers. Edge strength under the outlines against the outlines shifted by -6..+6 px:
  C00 (97,649 outline px) peaks at dx -1, dy +1 px; C02 (25,975 px) at dx +2, dy -2 px; one pixel is 0.05 mm at 19.7 px/mm. The picture layers (C04-C06) have a bounding frame with no edge under it, so this
  measure says nothing about them; their position rests on the correlation after refinement (0.68 / 0.84 / 0.88) and the look of the overlay.
- New tests: `test_app_version_header.py` (4, node), seven in `test_ruler_alignment.py` (notes and warnings, overlay with and without `located`, left behind never drawn). `tests/ui_dom.js` got `classList.toggle`.
- The wording "this layer was not engraved" stays for a check that was not found by pictures (REQ-050); it is replaced only when pictures found the work.

### 0.17.3: the picture cache version (REQ-056)
- [x] After deploying 0.17.2, `GET /api/pairs/105/overlay.png?size=1400` answered in 0.01 s and the downloaded picture had 0 light-blue pixels (the working-tree drawing: 40,502): the render cache served the picture drawn by
      0.17.1, because `RENDER_VERSION` was not bumped when the drawing changed. Bumped to 2; a test keeps the version in the key; full suite and a fresh GET of the overlay on the deployed server are the proof.


## 0.18.0 plan: photo engraving is the fourth section; grayscale scales "grey -> colour" from the operator's data, confirmed by a grey-ramp plate; time of every work (operator goal, 2026-10-21)

Operator's words (voice-typed): "четвёртым пунктом была фотогравировка ... цветная гравировка мне вообще не нужна, потому что это и есть векторная работа"; "по моим данным, выбирая сеттинги фотогравировки,
видеть, как она будет выглядеть. И мои эксперименты должны это подтверждать"; grayscale: "все статичные, кроме мощности ... если эти основные сеттинги не вокруг чёрного цвета, а вокруг какого-то другого, то изменение
мощности меняет цвет ... научился понимать, какой серый создает какой цвет"; "считал ... скорость выполнения каждой работы ... 3 часа она делается или 15 минут"; "обрати внимание, какое должно быть расстояние между
точками ... такое же расстояние, как и для цвета ... grayscale вообще не получится ... я нашел 0.0169, но может быть есть более удобный вариант"; "да, делай писатель слоя Image и пластину".

#### Evidence (read only: the live DB opened read-only, GET on 8765; scripts in the scratchpad)
- One laser (JPT M7 60 W), one lens (F-Theta 174, field 170), three Grade 5 titanium records. Grayscale works: pairs 88 Motorcycle and 93 Girl on a bike (Big Plate, Min 1 / Max 30, 150 mm/s, 60 kHz, 300 ns,
  0.0169 mm = 1500 dpi, chart-corrected) form one mode ("Mode A", 31 tonal points, P 1.9-29.1); pair 85 Inna-2 (Test Plate, 5-16.1 %, 128 mm/s, camera-relative, 13 points).
- Mode A changes colour with power, not only lightness: pale gold (P 2-9, L 76-82 b 14-21) -> gold (P 12.8: 72/4/26) -> violet-neutral (P 18.2: 53/2.5/-1) -> dark brown-grey (P >= 23.7: 43/-1/5). Ends dE 25-33.
- Repeatability of Mode A (88 vs 93): dark half dE 1.2-2.9, light half 8-16.
- The fill row of the Power x Speed plate (pair 95) has EXACTLY the settings of Mode A. Grayscale pixel vs fill at the same power: dark (P 24-29) dE 1.4-6.2; middle (P 16-22) 15-21; light and gold (P 5-15) 6-36.
  A power factor does not explain it (best x1.1: still 12-17). So a grayscale scale is measured with grayscale engravings; fills are not a predictor (answers Q-026 with numbers; the operator's remark on
  the line interval says why).
- Nothing writes `CutSetting_Img`; no grey-ramp plate exists; no photo job or plate shows its total time; no real job duration is stored anywhere (estimates only, DEC-075, never timed).
- The operator's own Image layers (reference for the writer): `CutSetting_Img type="Image"` with minPower, maxPower, speed, frequency (Hz), QPulseWidth, interval, ditherMode, dpi (= 25.4 / interval, rounded);
  `Shape Type="Bitmap"` with W/H = mm of the PNG at its own pHYs dpi, XForm scale + centre, Gamma/Contrast/Brightness/Enhance*, File, SourceHash, Data = base64 PNG (L or RGBA).

#### Order (the operator's ask first; each step tested on its own files while building, the full suite once at the end)
- [x] A. Navigation: 1 Эксперименты, 2 Карта цветов, 3 Векторная работа, 4 Фотогравировка (new section), then the rest. "Цветная гравировка" leaves the menu; its address stays (plan pages link to it).
      The banded tonal / colour-path form and the old preview stay reachable from the section; their addresses keep working.
- [x] B. Grayscale scales (the core): a scale = one grayscale mode (laser, lens, titanium, speed, frequency, pulse, interval, passes) with its measured "power -> colour" points from grayscale engravings only.
      Per scale: the colour bar over its measured power span, the grey -> colour bar for the chosen Min/Max with grey numbers (0-255) and power, the table "which grey makes which colour", where each point
      was measured, and the confirmation by experiments: each engraving against the curve of the OTHER engravings (dE per power band). Fills of the same settings are shown beside as reference, not used.
- [x] C. Preview of a picture on a scale: a plain picture (PNG/JPG) or a LightBurn file; Min/Max sliders inside the measured span; side by side with the prediction; the engraving time for the chosen size;
      download a LightBurn file with the picture on an Image layer with exactly these settings (needs D).
- [x] D. The Image-layer writer: `CutSetting_Img` + `Shape Type="Bitmap"` (PNG with pHYs at the layer dpi), read back by our parser AND compared tag by tag with the operator's real Image files.
- [x] E. The grey-ramp plate ("Шкалы серого"): a plate type with markers and cleaning first; each tile one Image layer in grayscale mode with a horizontal 16-step ramp (steps at the measurement's bin centres,
      white on the left), its own settings; two axes chosen from speed, line interval, frequency, pulse width, passes (default rows = interval 0.0127 / 0.0169 / 0.0212 / 0.0254 mm = 2000 / 1500 / 1200 /
      1000 dpi, columns = speed around 150 mm/s); Min/Max power shared. Engraved -> photographed -> the existing check measures each tile as a tonal profile -> each tile becomes a scale. Proven end to end on a
      synthetic photograph of the plate (check, accept, the scale appears with the right colours).
- [x] F. "Which grey for this colour": a colour picture -> the grey picture whose grayscale engraving on the chosen scale comes nearest (each pixel to the nearest colour the scale reaches); preview and download.
- [x] G. Time of every work: the photo preview and the downloaded file, every plan and plate page (`engraving_time.estimate`), with what the estimate leaves out.
- [x] H. Docs (MarkView feature through the tools), README 0.18.0, version, lessons, full suite (-n 12), backup + deploy to 8765, check on the real app (GET only), report with "reload (Cmd+R)".
      Done 2026-10-21: REQ-059, REQ-060, DEC-100..102 through MarkView; README 0.18.0; lessons; 1545 passed (-n 12, none skipped) on the final tree; backup
      `backups/titanium-before-0.18.0-20261021T192658Z.sqlite` (integrity ok); wheel installed with its dependencies; 8765 answers 0.18.0. GET only: 2 scales, Inna + Boris 1.65 h,
      vector screen 3.11 h, overlay of pair 104 redrawn (4.1 s, then 0.008 s from the cache) with every shape outlined.
- Ids: requirement numbers are global across features in MarkView (REQ-058 is vector-detail's), so this release is REQ-059 (photo engraving) and REQ-060 (time);
  decisions DEC-100 (scales from grayscale engravings only), DEC-101 (time per piece of scan line, 1 ms), DEC-102 (shared VertList / PrimList).

#### Review (2026-10-21)
- Built: A-G as listed; tests `tests/test_grey_scales.py` (11), `tests/test_engraving_time.py` (+4), `tests/test_lightburn.py` (+1), UI and i18n tests; the framed-ingest acceptance became a module
  fixture (the witness test depended on another test's side effect and failed when pytest-xdist put them on different workers).
- Found while timing works: the reader did not follow LightBurn's shared lists (`VertID` / `PrimID`): 222 of 574 paths of Inna + Boris 9_backup were open lines with no area, 8 stored files affected
  (DEC-102). Fixed in `lightburn._shared_lists`; overlays redrawn (`RENDER_VERSION` 3).
- Time model timed against the operator's jobs (DEC-101): Inna + Boris about 3 h at 150 mm and 1.5-2 h at 100 mm. Counting pieces of scan line from the shapes (edge extent / 2 x interval) at 1 ms:
  150 mm 3.11 h on the vector screen, 2.9-3.3 h by the files; 100 mm 1.5-1.65 h. The old 0.3 ms with 10 mm lines gave 1.2-1.4 h for the 100 mm file.
- Real data (Mode A): confirmation median dE 10.2, not confirmed: dark half 1-3 dE, light half 10-16; 10 fills of the same settings differ by up to 33.8 dE (reference only).
- Full suite: 1545 passed, none skipped, 2 min 38 s on 12 workers.
- Light half of Mode A (why it is not confirmed; analysis on an isolated copy, the live data only read):
  - Not the measurement: keeping only pixels whose picture is uniform within 0.3 / 0.5 mm (no blur mixing, no registration error) leaves the two engravings 10-20 dE apart at greys 135-255.
  - Not the LightBurn file: both Image layers have Gamma 1, Contrast 0, Brightness 0, the same Min 1 / Max 30, 1500 dpi.
  - Not the photograph's correction: in both chart-corrected photos the chart patches agree within 2.6 L, the steel ruler within 2.6, the background within 2.7.
  - Not the focus: the operator answered (2026-10-21) that both were engraved at the same focus height.
  - What is seen: at the same greys Motorcycle reads L 72-85 (lighter at the top of the plate than at the bottom), Girl on a bike L 64-71 everywhere; the dark greys
    read L 38-44 on both, everywhere. The holders differ (light grey under Motorcycle, dark grey under Girl: 69 vs 30 L).
  - Next, by the operator: photograph both plates again in the same holder, in one photograph or one after the other, and add the photos to their experiments
    ("Добавить фото"); then engrave the "Шкалы серого" plate. Same plates reading alike in the same holder means the photographs were the cause; reading apart
    means the light end of grayscale on these plates is not repeatable, and the scale must show that spread instead of one colour.
- Open for the operator (answered with a default, not blocking): pure white at Min power (the plate's first step is white: the photograph decides); a convenient interval (the plate's rows decide: the one
  with the widest colour range and distinct steps); the pulse width 300 ns is not one of the laser's steps (250 / 350): the laser keeps the last valid one, so what these works really used is uncertain.

## 0.18.1 plan: the grey-ramp plate saved by LightBurn is read whole (operator added the photo of TCE-A93B49E6, 2026-10-22)
The plate (pair 107, IMG_3376.DNG) aligned by its markers, but 3 of the 4 tiles at 250 ns gave "0 pixels" and the 4 tiles at 350 ns were read with no picture.
Two causes, found on an isolated copy (`scratchpad/plate107`, the live data only read):
- LightBurn 2.2 stores a picture placed twice once: the second Bitmap of a row has `Data=""` and the first one's `SourceHash`. The reader saw no picture there.
- `lightburn.normalize_saved_orientation` (LightBurn rewrote `MirrorY` and reflected the XForms) mirrored the outlines only: the picture's own matrix (and the holes) stayed
  in the saved axes, so what a picture strikes landed mirrored about the plate's centre (tile 8 at rows 1171-1283, its struck mask at 541-654) and missed its own tile.
- [x] A. A Bitmap without `Data` takes the picture stored with an earlier object: by the same file name (as before), otherwise by the same `SourceHash` (DEC-103). Done in the existing
      pass of `lightburn.parse_bytes`, not as a second mechanism in `_shared_lists` (tried first, reverted: the file-name pass already existed).
- [x] B. `normalize_saved_orientation`: reflect the holes and every picture's matrix with the outline, so the picture stays on its shape.
- [x] C. Test: the grey plate saved the way LightBurn 2.2 saves it (MirrorY rewritten, XForms reflected, each row's picture stored once) measures every tile, all 16 steps,
      each step its drawn colour; reader tests for the shared picture and the reflected matrix.
- [x] D. Version 0.18.1, README, MarkView DEC-103, lessons; full suite 1548 passed (-n 12, none skipped); backup
      `backups/titanium-before-0.18.1-20261022T010813Z.sqlite` (integrity ok, 87 pairs, 2108 observations); 8765 answers 0.18.1.
- [x] E. Re-measured with the operator's approval ("Перемерить заново" pressed in a second MarkView tab): pair 107 -> 108, 8 of 8 tiles, 16 of 16 steps each; 21 pairs, no file missing.
- [x] F. Read the 8 scales: neither pulse reproduces Mode A on the 0.0169 row (below).

#### Review (2026-10-22)
- Incident: the first reproduction ran `remeasure_pair` on a copy whose paths still pointed into the live files folder; accepting the revision on the copy deleted the live `.lbrn2` and DNG of
  pair 107. Restored byte-identical within minutes from the copy taken just before (the live database was never written); lesson added; `scratchpad/tools/safe_copy.py` rewrites every stored
  path of a copy and refuses one that still names the live folder.
- What the plate shows (chart-corrected, 16 steps per tile, Min 1 / Max 30):
  - Within the plate colour follows energy per area: the bluest step sits at P / interval = 535-686 on every row (one step is 1.9 %). Wider intervals spread the sequence over more steps and
    saturate it: at 0.0254 gold b +30..+38 at P 7-11, blue b -22..-28 at P 14.5-16.5; at 0.0169 the whole sequence is squeezed into P 5-11.
  - Against Mode A (Motorcycle, Girl; 0.0169, 150 mm/s, 60 kHz, entered as 300 ns): light half 24-29 dE median, dark half 10-13, for 250 and 350 ns alike. The plate is bare at P 2, straw at
    4, gold at 5.5, violet and blue at 7-11, light blue at 13, then grey; the works stay straw (L 65-82, b +14..+28) up to P 13, turn brownish at 15-17 and grey after, never violet or blue.
  - Same layer settings; differences: line length 150 mm (works) vs 38 mm (tile), cleaning interval 0.04 vs 0.05, the real pulse of the works unknown (operator: "Don't know").
- Next (operator's choice, 2026-10-22): one picture on one plate scale engraved twice from "Картинка на шкале", 38 mm and 100 mm wide. The small one tests the prediction in the plate's own
  geometry; the large one shows whether size (line length, heat) moves the colours. Both are compared with the plate's scale by the confirmation the scale already shows.

## 0.18.2 plan: the picture stays when another scale is chosen, and its prediction follows every change (operator, 2026-10-22)
Operator: "когда я выбираю картинку, а потом меняю шкалу, то он картинку удаляет. Не удаляй картинку, меняй шкалу и он динамически должен менять как будет выглядеть картинка."
Cause: choosing a scale replaces the scale panel with `scaleDetail(sc)`, and each panel built its own `pictureBlock`: the chosen file, width, "подобрать серые" and the prediction
went with the old panel. The server keeps an uploaded picture with the scale it was sent for (the cache item holds the mode), so on another scale the file is sent again.
- [x] A. One picture block for the whole screen, handed to each scale panel: the file, width and "подобрать серые" stay when another scale is chosen, and the picture is predicted on
      the new scale (its Min/Max) without pressing anything.
- [x] B. The prediction follows every change by itself: choosing the file, the width, "подобрать серые", Min/Max, the scale. One upload per (scale, file, by-colour); later changes
      re-render the kept upload; an answer for an earlier state is dropped. "Показать на титане" stays as "send the file again" (after a restart the server forgets uploads).
- [x] C. Test in node over the screen's own code: choose a picture, change Max, choose another scale -> the same file is kept, a second upload carries the new scale's settings
      and Min/Max, its prediction is shown; a late answer of the old scale does not replace the new one.
- [x] D. Version 0.18.2, README, MarkView bug, full suite (-n 12, none skipped), backup, deploy, check in the operator's app.
      Done: 1551 passed (-n 12, none skipped); the 3 new tests fail on 0.18.1 and pass now; checked in a browser on an isolated copy (port 8768): the file stays on another
      scale, colour choice and Max re-predict; backup `backups/titanium-before-0.18.2-20261022T020208Z.sqlite` (integrity ok, 88 pairs, 2118 observations); 8765 answers 0.18.2.

## 0.19.0-0.21.0 plan: photo engraving on one screen, "ask AI" on a photo, photo-engraving colours in the vector palette, every section on one screen (operator, 2026-10-22)
Requests: "в фотомастерской или векторной мастерской ... попросить AI что-то поменять ... всё как есть, черно-белое ... платье сделать фиолетовым или красным, ярким ... кожу сделать
равномерно светлой ... он должен будет подобрать такой серый цвет"; "фотогравировка нам дает неплохие еще цвета. Ты должен их цвета туда тоже добавить"; "сделай фотогравировку ... на один
экран. Так же, как и все другие. Вообще, все ... на один экран"; "насчет других скоростей ... чтобы получить другие совершенно шкалы".
Answers (2026-10-22): parts of a photo = a people segmentation model (MediaPipe multiclass: background, hair, body skin, face skin, clothes, other); AI = OpenAI as now (`research.openai_client`);
photo-engraving colours = the vector work palette; next engraving = both the picture at 38 / 100 mm and a plate of speeds 100 / 150 / 250 mm/s.
What exists: AI only in vector work (`ai_colouring.py`, free text, photo sent only with permission); `segment.py` colour regions, `faces.py` faces; photo engraving keeps grey, BGR and Lab
of an upload (`prediction_store.decode_upload`); `grayscale.grey_for_colours(lab, curve, lo, hi, levels=...)`; the vector palette leaves image-layer greys out (`palette._left_out`); the
one-screen frame `.os` (styles.css section 15) is used by experiments, colour map, experiment page, laser model, knowledge.

### 0.19.0: photo engraving works, like vector works (operator, 2026-10-22: "мне нужны работы, так же как и в векторной гравировке"; "расширяй до конца - не помещаются надписи")
What vector works are: rows of `plan` (mode "Vector job", `data_json`), a list `#/vector` (card: picture, name with a pencil, size, colours, last engraving result, changed at; Open,
Make a copy, Delete), a new work `#/vector?new=1`, a one-screen workspace `#/vector?plan=ID` (head: "← Мои работы", name, "Сделать копию", "Файл LightBurn"), the TCE identifier in the
exported file, so the photograph of the engraving finds its work (REQ-013, DEC-090) and the work shows promised against engraved.
- [x] A0. One-screen frame for photo engraving (`.os ge`: scales | picture and prediction | tabs) and full window width for every `.os` page; no column or tab cuts text at 1771 and
      1372 px (checked on the copy). It becomes the workspace of one work.
- [x] A. Store: `photo_work.py`, a `plan` row of a new mode "Photo engraving work": the picture stored once (`cv._store_image`), name, laser, lens, titanium, the scale (its settings),
      Min / Max, width, colour choice, an identifier; list, view, create, change settings, copy (own picture copy, new identifier), rename, a list picture. Delete is the plans' own
      `DELETE /api/plans/{id}` (a work nobody photographed is removed, with its cached pictures); such a work is not listed as an experiment.
- [x] B. API `/api/photo-works`: list, create (upload), get, settings, copy, rename, `thumb.png`, `preview.png` (picture and prediction), `picture` (the upload), `export.lbrn2`
      (grayscale Image layer; no identifier in the file yet, DEC-104: that is 0.19.2), time. Pictures through the render cache, keyed by everything they are drawn from, the
      scale's measured points included. Shared with the grey-scales picture: `prediction_store.check_width`, `file_parameters`, `predicted`.
- [x] C. UI: "Фотогравировка" opens on "Мои работы" (cards as in vector) with "Новая работа", "Шкалы серого" (the scales overview), the plate button and the two links; a new work:
      picture, name, width (the scale is chosen in the work); a work opens the one-screen workspace: choosing a scale, Min / Max, width or colour choice saves the work and re-predicts.
      Changes go to the server one after another in their order, the last answer is shown; a work whose scale is no longer measured says why and offers the measured ones. The
      scales page (`?scales=1`) has Min / Max, the bar and the grey table in the centre, confirmation, points and kinds on the right, and "Новая работа на этой шкале". The rename
      pencil of vector works takes a base path (`VectorWorkspace.renameButton(..., '/photo-works')`).
      Checked on the copy (8768): list, open, switch scale (saved, Min / Max become its span, the picture stays), Max saved, rename, the dialog; no cut text and no page scroll
      at 1675 and 1080 px. The 0.19.1 groundwork (`people.py`, `picture_rules.py`, the model, the rules in `prediction_store`, `ai_colouring` instructions) is kept out of 0.19.0
      (scratchpad `groundwork-0191/`) and comes back for 0.19.1.
- [x] D. Tests (store, API, UI in node: list, open, switch scale keeps the picture, copy, rename, delete), README, MarkView REQ, full suite, backup, deploy, check in the app.
      Done 2026-10-22: `tests/test_photo_works.py` (13), `tests/test_photo_engraving_ui.py` rewritten (6); README 0.19.0; REQ-061 approved, DEC-104 accepted; full suite 1567 passed
      (-n 12, none skipped); backup `backups/titanium-before-0.19.0-20261022T025408Z.sqlite` (integrity ok, 88 pairs, 2118 observations, 5 plans); wheel installed with its
      dependencies; 8765 answers 0.19.0 and shows "Мои работы" (GET only: no works yet, 10 scales).
### 0.19.1: "Попросить AI" on the picture of a work
- [x] Spike: MediaPipe multiclass selfie model converted once to ONNX, run by OpenCV (`models/selfie_multiclass_256x256.onnx`, Apache 2.0; 0.06-0.09 s per picture). DEC to record.
- [x] Parts (`people.py`, done in code), rules -> greys (`picture_rules.py`, done in code), the rules stored in the work and applied to preview and file; an "AI" tab: the wish, the parts
      table (share, colour, rule, editable by hand), the overlay; the AI (`ai_picture.py`, OpenAI, one retry) proposes the rules. Tests with a fake client, release.
  Plan (2026-10-22, after 0.19.0 went live; REQ-062, DEC-105):
  - [x] E1. Work data: `rules` (checked by `picture_rules.check`; a hand rule may give `hex`, turned into L*a*b* here), `ai_photo` (permission to send a reduced picture,
        off by default), `ai` (the last request: wish, photo sent, note, when, the rules before it). Older works get the defaults. `update` takes `rules` and `ai_photo`.
        The part scores are computed once per decoded picture (kept with it). The preview, the list picture and the file follow the rules (their keys include them); the
        view reports per rule its share and how near its greys come (median dE). The time does not change: in grayscale every pixel is scanned.
  - [x] E2. `photo_work.parts` (each part found: share, mean colour) and `parts_picture` (the preview tinted by part, render cache). `ai_picture.py`: the brief (wish, parts,
        16 greys of the scale with their colours, the range of the near-grey greys, the current rules), the instructions, the check (rules by `picture_rules.check`, parts
        the picture does not have dropped), one retry through `ai_colouring.choose`; `photo_work.ask_ai` saves the rules, the note and the rules before.
  - [x] E3. API: `GET /photo-works/{id}/parts`, `GET /photo-works/{id}/parts.png`, `POST /photo-works/{id}/ai`; settings take `rules`, `ai_photo`. Translations.
  - [x] E4. UI: tab "AI" in the work: the wish, "send a reduced picture" (off), "Попросить AI" (off with the reason when there is no key or library), the AI's note with
        "Вернуть как было"; the parts table (part, share, colour, rule select, target colour for "colour" / "one tone", how near); the parts over the picture.
  - [x] E5. Tests: rules (unit, a made-up curve), parts with made-up model scores, the work's rules through the API (preview, file, copy, refusals), the AI with a fake client
        (good answer, one bad then good, two bad: nothing changes, the picture sent only when allowed, no key), UI in node. README, MarkView, full suite, backup, deploy.
        Done 2026-10-22: `tests/test_picture_rules.py` (15), `tests/test_photo_works.py` +16 (29), `tests/test_photo_engraving_ui.py` +3 (9); README 0.19.1; REQ-062
        approved (DEC-105 accepted earlier). Found on the copy and fixed before release: the list of works failed on a work saved by 0.19.0 (no rules; defaults now filled
        in for the list too, test added); the answer of the AI no longer overwrites a change made while it answered (the work is read again before saving, test added);
        the rule select was cut ("Один т") - the closeness column is now "ΔE к цели". Real check on the copy (8768, work 26 "Лицо"): the model found background 13 %, hair
        54 %, body skin 7 %, face skin 26 % in 0.26 s; the real AI on «всё как есть, черно-белое, а кожу сделать равномерно светлой» (numbers only, 6 s) answered
        background and hair black and white (ΔE 6.0 and 6.5), body and face skin one light colour L 80 (ΔE 3.2), features kept; «Вернуть как было» put the rules back.
        Review: the instructions now tell the AI that "one tone" erases the eyes and lips inside face skin, so even light skin is a target colour.
### 0.19.2: undo and redo in a photo work; ask the AI again from the plain picture
Operator, 2026-10-22, on the live 0.19.1: "Нет возможности перегенерировать с картинки, отменить действие". The audit shows four AI requests on "Inna Portrait" within a minute,
each building on the rules before it, then the work deleted and a new one made. Plan (the vector editor's undo, DEC-077, is the model):
- [x] U1. Server: `undo` / `redo` stacks in the work (50 steps). A step is the work's state that decides what it engraves: scale (with laser and lens), Min, Max, width, colour
      choice, rules, the AI's last answer. Each change that alters it pushes a step and clears redo; the permission to send the picture is not a step (undo never re-enables
      sending). `POST /photo-works/{id}/undo`, `/redo`; the view says how many steps each way. A copy starts without history. Older works get empty stacks.
- [x] U2. AI: `POST /photo-works/{id}/ai` takes `fresh`: the AI starts from the plain picture (no current rules sent; its answer replaces them).
- [x] U3. UI: «Отменить» / «Повторить» in the head of the work (disabled with nothing to undo or redo, Ctrl+Z / Ctrl+Shift+Z outside text fields); after a step the scale,
      Min/Max, width, colour choice, rules and note on screen are those of the work. AI tab: «Попросить AI» (from the current rules), «Заново с картинки», «Все части как есть»;
      «Вернуть как было» goes (undo does it and more).
- [x] U4. Tests (API: steps of settings, rules and AI, permission not a step, no-op not a step, empty stacks refused, redo cleared by a new change, copy without history; AI fresh
      sends no rules; UI in node: buttons, keys, the sliders follow an undo, fresh, all as is), README, version, lesson, full suite, backup, deploy, commit.
      Done 2026-10-22: `photo_work.step`, `STATE`, `UNDO_DEPTH`; `POST .../undo`, `.../redo`; `ai` takes `fresh`; head buttons and keys; AI tab «Заново с картинки» and «Все
      части как есть»; tests +5 API (34), +2 UI (11), the test DOM has `isConnected`; README 0.19.2, REQ-063 approved, lesson added. Checked on the copy (8768, work 26): a hand rule and
      Max 25 undone one by one (Max back to 30 on the slider), Ctrl+Z / Ctrl+Shift+Z; the real AI asked "волосы чёрно-белые", then "кожу светлой, остальное как есть" (hair kept,
      skin added), then «Заново с картинки» (skin only, hair as it is again); 4 steps to undo; nothing cut at 1771 px.
### 0.19.3: the engraving of a photo work checks its prediction
- [x] The photograph of an engraved photo work (its file carries the identifier) is linked to the work; the work shows predicted against engraved per grey level, and the scale's
      confirmation counts it. Tests, release.
  Plan (2026-10-22; how ingest works was mapped first: identifiers are read from the file's Notes `TCE1:<id>` by `ingest._load_identified` for any plan; a checked pair keeps
  the plan in `pair.plan_id`; an Image layer in grayscale is measured as a tonal profile of 16 grey bins; an accepted one already feeds its scale and its confirmation):
  - [x] V1. The file names its work: `plans.export_picture(..., identifier)` writes `TCE1:<identifier>` into the Notes; `photo_work.export` passes the work's identifier.
  - [x] V2. End to end: a photograph of that file links to the work by itself (no plan chosen), is measured as a tonal profile and, accepted, counts in the scale.
  - [x] V3. The check of one engraving, as the scale's confirmation does it (DEC-100): each grey bin of the engraving against the curve of the OTHER engravings at the settings
        it was engraved with (leave one out; the comparison is factored out of `grayscale.confirmation` so both use it): grey, power, predicted colour, engraved colour, ΔE;
        median, max, share within 5 ΔE, confirmed or not; said plainly when there is nothing else to compare with, or the settings differ from the work's scale.
  - [x] V4. API `GET /photo-works/{id}/engravings` (every photograph linked to the work: its state, and the check once accepted). UI: tab «Гравировки» in the work with
        «Загрузить фото гравировки» (the upload screen with this work) and per engraving the summary and a strip of greys, predicted beside engraved.
  - [x] V5. Tests (export identifier; ingest end to end with a made-up photograph; the check numbers; API; UI in node), README, REQ, version, full suite, backup, deploy, commit.
  Review (2026-10-22):
  - Built as planned except the place of the engravings: they open the «Подтверждение» tab instead of a tab of their own (five tabs already fill the narrow column, and it is
    the same subject: the scale's confirmation follows right below).
  - Found on the real scale, not in the synthetic one: a free picture was oriented and accepted by the rank correlation of grey and lightness. Work 28's scale (150 mm/s,
    1-30 %) does not darken step by step, so a photograph drawn exactly from it was read upside down and dropped as "weak". The operator chose "trust the picture match"
    (DEC-106): a photograph aligned by matching its file's picture reads it as matched, and the match is the evidence (`ingest.PICTURE_ALIGNMENTS`); every work with a picture,
    accepted pairs unchanged until re-measured. On the copy: no points -> 16 greys, median 2.8 dE, confirmed. The regression test uses colours that rise and fall along the greys.
  - New paths a photo-work pair opened, fixed: its analysis report (the plan has no `layers`), the experiment page (a «Работа фотогравировки» block that opens the work and
    downloads its file instead of the plate links), the upload and check screens (a line naming the work), the mode name in Russian.
  - Known limitation: bins of 16 greys of a slightly blurred photograph mix neighbouring colours where the titanium colour changes fast with power; on the copy two bins near
    13-15 % showed 15-19 dE for a photograph drawn exactly from the scale while the median was 2.8. Proposed next: compare like with like (the predicted colour of every
    pixel, blurred as the photograph is) - to be agreed with the operator.
  - Open question for the operator: «Удалить эксперимент» of a photographed work (vector or photo) deletes its checks and then archives the work itself; on the isolated copy
    work 28 was archived this way at 03:53 UTC (restored on the copy; the operator's data untouched).
  - The operator's goal ("my experiments must confirm it") is NOT met yet and cannot be met from the data there is: the earlier real engravings were re-read under DEC-106
    (pairs 85, 88, 93 were already read as matched: flip False, evidence clear, so re-measuring changes nothing); Mode A's two works still disagree in the light half
    (10.2 dE, 0.18.0 review) and the plate does not reproduce them (0.18.1 review). It waits on the agreed experiment: work 28 «Inna Portrait» (plate scale 150 mm/s,
    60 kHz, 350 ns, 0.0212 mm, Min 1 / Max 30) engraved at 100 mm and a copy at 38 mm, files downloaded from 0.19.3 on, photos uploaded from the work's «Подтверждение».
    When the operator says they engraved: read pairs > 108 read-only and report each work's check.
### 0.21.0 (was 0.20.0; moved behind the size work, 2026-10-22): photo-engraving colours in the vector palette
- [ ] G. Palette entries from the grey scales (each measured power of a scale); a region given one is written as an Image layer of one even grey with the scale's settings
      (Min = Max = that power); time per cm2; the colour picker says where it comes from. Tests, release.
### 0.23.0 (was 0.21.0, then 0.22.0: photo zones came first): every section on one screen
- [ ] H. Measure every menu section and its pages at 1421 x 951 (copy of the data); move those that scroll onto `.os`; report the heights before and after. Tests, release.

## 0.19.4-0.20.x plan: the size of an engraving changes its colours; previews at the real size; a colour choice that keeps the drawing; rename an experiment (operator goal, 2026-10-22)
Requests: «в экспериментах у меня нет возможности поменять имя эксперимента»; «цвета дичайше меняются, осветляются в зависимости от размера картинки ... на маленькой
картинке 100 на 100, на шероховатой поверхности цвета выглядят намного темнее ... черный на лбу не должен быть черным ... губы ... вообще не видно ... Ты всегда должен показывать
какие-то контуры ... подумай, как все это дело поменять, чтобы разукрашивать красивее в зависимости от размера, чтобы мы могли сказать, как оно будет»; and «фотографировочная
работа, векторная работа, если используются эти цвета ... учитывали размер ... и показывали бы в превью правильную версию».

Findings (read-only on the operator's data and its LightBurn files; scratchpad `look/`):
- Pair 110 = the «Inna Portrait-P1-30» file (no identifier: downloaded before 0.19.3) stretched in LightBurn to 150 x 150 mm (bitmap 1800 px, 1198 dpi), a cleaning layer
  C01 run first (priority 0) as on the grey-ramp plate, Big Plate 150, Min 1 / Max 30, 150 mm/s, 60 kHz, 350 ns, 0.0212 mm. Pair 109 = the same bitmap at 100 x 100 mm on
  Small Plate (rough). The scale of the work was measured on the grey-ramp plate 108: ramps 38.4 x 4 mm.
- Colour against power, 38.4 mm ramp vs 150 mm picture (same plate kind, same settings): at 150 mm the first oxide colours come later - 4.9-14.5 % straw/gold (L 78-87,
  b up to 40) where the ramp gave violet and dark blue (L 38-45); blue at 16.5-18.4 %; the darkening at 20-30 % nearly the same (L 63->38 vs 71->43). Median 14.2 dE; no single
  power factor explains it (best k = 1.0). 109 (100 mm, rough Small Plate) is darker than both; material and surface differ, so its size effect cannot be separated.
- Per pixel (blurred, like with like), the file's greys drawn with the colours measured at 150 mm match the 150 mm engraving: median 4.9 dE, 78 % within 10 dE; drawn with the
  38.4 mm scale: median 15.8 dE, 26 % within 10. At one size the colour is a function of the grey; the size is the missing dimension. (In-sample: the 150 mm colours come from
  this engraving; a second engraving at the same size is the real check.)
- The black forehead: face skin had no rule; the nearest-colour choice put the forehead in the 20-30 % neutral band (predicted dark grey at 38.4 mm, near black at 150 mm).
  The lips got the same grey as the skin around them. Both were visible in advance with the 150 mm scale.
- Physics (hypothesis to confirm): the time between two passes over a point is the row length / speed. Short rows (a 38.4 mm ramp, a 5 mm test patch) keep the heat ->
  colours further along the oxide series; long rows (a 150 mm picture) cool between passes. Bidirectional scanning makes the edges of a row hotter than its middle; the 150 mm
  picture had too few flat areas near its edges to measure that (inconclusive).
- Prototype (scratchpad `proto_colouring.py`, 150 mm colours): lightness first (the picture's light and dark kept in order over what the scale reaches, local contrast over
  1.5 mm raised), then hue -> lips, nose, eyes and forehead read like the photo; contours that were still lost: 0.02 % of the picture.

### 0.19.4: rename an experiment (REQ-065)
- [x] `experiments.rename(store, key, name)`: a plate or work - its plan's name; a finished work without a plate - its engraving's title (all its photographs); stripped, blank
      refused, the same name writes nothing, one audit row `experiment_renamed`. `POST /api/experiments/{key}/rename` answers as the rename of a work.
- [x] The pencil beside the title of the experiment page: the shared rename dialog of works (`VectorWorkspace.renameButton(..., '/experiments', 'experiment')`, its words).
- [x] Tests: 3 backend (plan, engraving with its re-photograph, API 422/404/200), 1 screen in node. Walked on a copy (8768): renamed, list shows it, one audit row.
- [x] README, version, full suite, backup, deploy, REQ-065 approved. Done 2026-10-22: full suite 1617 passed (-n 12, none skipped; it first caught the
      untranslated "give the experiment a name" - translated); backup `backups/titanium-before-0.19.4-20261022T103107Z.sqlite` (integrity ok, 90 pairs, 2120
      observations, 9 plans, latest pair 110); wheel installed with its dependencies; 8765 answers 0.19.4 and serves the route and the pencil.

Order (operator, 2026-10-22, asked with three options): "Photo and vector together" - one release 0.20.0 with the size in photo works and vector works (S1-S7 and
W1-W4 below), the colour choice 0.20.1 after it.

### 0.20.0: the size is part of every colour measurement and prediction - photo works (S) and vector works (W) together
Map (subagent, 2026-10-22): points come only from `check.layers[].tonal.bins` (`prediction_store.collect` 160-189) and carry no size; the ramp width is reachable through the plan
(`layers[i].ramp.width`, matched by layer name as ingest.py:2370), a photo engraving's picture width only through its LightBurn file (`Region.width`, an axis-aligned box);
`photo_work._key` has no `width_mm`; the grey-ramp plate caps a plate at 100 mm (`capability_plates.preview` 930-938), so a 150 mm ramp does not fit; `grayscale.*` and
`picture_rules.greys` take a curve and need no change.
- [x] S1. Row length of a measurement (`row_mm`): the scanned length of a row through it - a ramp's width; a picture's width (its height when the scan angle is 90 deg); the tonal
      report records it from now on, and `collect` derives it once for older pairs (from the plan's ramp, else from the stored LightBurn file; cached by path and mtime; nothing
      written to the operator's database). `Point.source["row_mm"]`.
- [x] S2. A curve at a row length: `curve_for(store, mode, row_mm=None)` - the measurements at that length (within 10 %), else between the two nearest measured lengths (Lab
      interpolated at each power in log length), else the nearest, marked "not measured at this size" with the measured lengths. Without `row_mm` as today (all points).
- [x] S3. Photo work: the curve at the work's width everywhere - scale shown in the work, colour choice, rules, preview, list picture, file, AI brief, the check of its engravings
      (`engraving_check` at the engraving's own row length; another size is "not comparable", not a failed confirmation). `_key` includes the width. The work says at which
      measured widths its scale was made and warns when its width is outside them. Changing the width redraws.
- [x] S4. Grey-scales page and cards: the widths each scale was measured at; the scale shown at a chosen width.
- [x] S5. Grey-ramp plate: a new axis "ramp width, mm" (e.g. 20 / 40 / 70 / 100 / 150 on one setting), per-row ramp width in layout, labels, cells, metadata; the 100 mm cap
      becomes the plate size the operator gives. The check reads each ramp at its own width (already per ramp).
- [x] S6. "Проба на ширине работы" in a photo work: a small plate file - one ramp of the work's width x 5 mm at the work's scale settings, with markers and QR - so the scale is
      measured at that size before the picture is engraved.
- [x] S7. Tests with synthetic ramps whose colours depend on row length like 108 vs 110 (and a size between them); walk on a copy of the real data (scale of work 28 at 150 mm
      must reproduce the 150 mm engraving; at 100 mm interpolated and said so); README, MarkView REQ/DEC, full suite, backup, deploy.

### 0.20.1: a colour choice that keeps the drawing, and contours always shown
- [x] C1. "Сохранить рисунок" (the default for a picture chosen by colour; "Ближайший цвет" stays as an option): the picture's lightness stretched in order over the lightness the
      scale reaches at the work's size, its local contrast over 1.5 mm (physical, so it follows the size) raised, then the grey whose colour is nearest with lightness counted
      four times; greys where the colour changes fastest with power are avoided for large areas (they shift most with heat).
- [x] C2. Contours: where the picture has an edge (12 dE across 0.3 mm) that the predicted engraving loses (under 6 dE), the edge is drawn 0.3 mm wide in the grey of the scale
      that contrasts most with its surroundings; on by default, a switch in the work; the preview and the file are the same picture.
- [x] C3. Part rules act on top as now. Tests (lips darker than skin stay darker; a lost edge is drawn; the file equals the preview), walk on a copy with «Inna Portrait» at
      150 mm, README, MarkView, release.
- As built (REQ-067, DEC-108; `drawing.py`): C1 as planned; flat areas (local L* std under 2) take among the 8 nearest greys within 3 dE the one whose colour changes
  slowest with power. C2 changed on the real portrait: 12 dE across 0.3 mm drew skin texture and white "teeth" in the mouth, so an edge is 8 dE across 0.5 % of the
  picture's width (at least 0.3 mm), found at 10 px/mm, kept only if it reaches 1 mm; the line is the darkest grey, or the lightest on a light ridge or where the dark one
  would not contrast by 15 L*. Order: colour choice, part rules, contours (none in parts with an "even" rule), the same code for the preview (800 px) and the file
  (layer DPI, at most the picture's own). `usable_greys` is shared with `grey_for_colours`. RENDER_VERSION 5.

#### Review of 0.20.1 (2026-10-22)
- Tests: `test_drawing.py` (forehead light, lips darker, one lightness not stretched, steep greys avoided only in flat areas, contours drawn at 8 and 25 px/mm, kept /
  spared / speck not drawn, light line on dark, no usable grey), photo-work API (defaults, change and undo, an old work without the keys, the file equals the preview
  at twice its pixels - the file's bitmap is stored bottom row first), UI (select and switch saved, texts).
- Walk on a copy of the live data (8768): «Inna Portrait» 100 mm - forehead light grey, the mouth line dark, the lower lip darker than the chin, order 98 %, contours
  0.04 %; 150 mm (measured there) - order 98 %, no edge lost; «Ближайший цвет» at 150 mm - 0.2 % outlined, the caption says «и контуры».

### 0.20.2: the skin light and even, features kept; no lines on the plain picture (operator, 2026-10-22, after 0.20.1; plan approved)
Operator: "белые секции делает непонятные ... раньше этого не было"; "в превью есть градиент в цвете кожи, в гравировке градиента вообще никакого нет ... квадратные
пятна ... практически черные"; "осветлил кожу ... ровным слоем, ровным градиентом ... выделенные губы, выделенные основные черты лица". Contours: "удаляй ... или
включить/выключить, но точно не для такой фотогравировки". Causes: (1) contours were on for every work, the plain picture too; on a dark scale every edge is "lost" and
was drawn in the lightest grey, broken into dashes where the test flickers; (2) the 0.20.1 choice took each pixel's grey from anywhere on the scale, so neighbouring skin
pixels landed on distant powers (grey-blue next to tan); the plain picture puts the skin on the flat light end and the shadows on the dark drop (the engravings 109/111).
- [x] D1. «Сохранить рисунок» lays the picture's tones along one path of the scale: from its lightest grey to its darkest in power order, lightness never rising, the
      sum of squared colour steps smallest (a hue swing at one lightness is skipped). The picture's lightness is smoothed edge-preserving over 0.25 mm (JPEG blocks,
      skin grain), its contrast over 1.5 mm raised by 0.5, stretched 1-99 % and mid-tones lifted (t^0.8); each pixel takes the path grey of that lightness. The picture's
      hues are not matched (that is «Ближайший цвет»). Prototype on «Inna Portrait» (live scale, 100 and 150 mm): order 0.99, the skin an even gradient, lips and
      features kept, no blue in the shadows.
- [x] D2. Contours off by default and drawn only when the greys are picked by colour; the switch is disabled for the plain picture.
- [x] D3. Tests (path skips a hue swing; a gradient gets neighbouring powers; grain does not become spots; one lightness unchanged; contours only with picking), UI
      texts, RENDER_VERSION 6, README, MarkView, walk on a copy (every scale of the operator, both widths), full suite, release.
- As built (REQ-068, DEC-109): `drawing.path` (dynamic programming over greys in power order, lightness rising at most 0.5 L*, least sum of squared
  colour steps) and `drawing.choose` (bilateral 0.25 mm / 6 L*, detail 1.5 mm x 0.5, stretch 1-99 %, t^0.8); the flat-area rule of 0.20.1 is gone with its constants.
  `_order` ranks ties together (scipy Spearman): on a three-tone picture the arbitrary ranks gave 0.79 for a perfect order. `picture_item` keeps contours only with
  `by_colour`, so the preview, the file and the report agree; RENDER_VERSION 6.
- Review (2026-10-22): the live portrait through the product code on all 11 scales of the operator at 100 and 150 mm - order 0.99 on each, skin even, lips and features
  kept, preview 0.07 s, file (1800 px) 0.5 s; one scale (300 ns / 0.0169, P6-14) reaches only L* 4-15 and stays dark. Walk on a copy (8768): picking on - «Рисунок
  сохранён: ... из 160 серых (L* от 88 до 41) ... 99 %», contours off; picking off - the switch and the choice disabled, «Картинка (как её видит LightBurn)», no lines.
- Waiting for the operator: "new work" in photo and vector engraving offers every way of creating one, and a photo work without enough data can start a test plan
  (pictures about 50 x 50 mm at several settings, engraved and photographed, as examples) - the operator's message continues ("продолжение следует").

### After 0.20.2: the main colour of the drawing, the cleaning layer in a picture's file, the preview's titanium (operator, 2026-10-22; plan to approve)
Operator: "возможность поменять общую тональность ... оно желтоватое всё ... столб сзади в более тёмной, синей тональности, кожа чуть-чуть светлее, очки красные ...
не напрямую, а именно основной цвет, который вокруг бы всего строился"; "когда генеришь LightBurn file - не забывай про cleaning layer"; a screenshot of
«Предпросмотр фотогравировки» with the work's file «Inna Portrait-P1-17.lbrn2» on «Small Plate»: "в этом режиме цвет ещё не измерялся".
Evidence (copy of the live DB, scratchpad `c3`):
- The preview: the file's mode (150 mm/s, 60 kHz, 350 ns, 0.0254) is measured on «Big Plate 150» only (the work's scale); on «Small Plate» it never was, so the refusal
  is right. With «Big Plate 150» the same file is predicted. The page starts with no titanium chosen and does not say where the mode is measured.
- The cleaning: `plans.export_picture` writes the picture alone ("no mirroring, no cleaning, no markers"), for the photo work and for «Картинка на шкале». Plates and
  vector works clean first on C00 (`plans.clean_layer`, CLEAN-CROSSHATCH-P20-F48-V2000-PW200-I0.05); the scales were measured on cleaned plates. The upload of a work's
  photograph already knows a CLEAN-CROSSHATCH layer (role "pre-test cleaning witness"), and a work finds its picture layer by its tonal profile, not its index.
- The main colour (prototype `c3/tone.py`, page `c3/page/index.html`): on the work's scale the colours form three families that a path can follow without a jump
  (steps of at most 5 dE, lightness never rising): gold-brown-red-violet (L* 80-37), light grey-light blue-blue-violet (L* 73-37), silver grey (L* 73-45). The other
  scales of the operator have two or three (one, P6-14, only dark grey). A main colour picks the family through it and lays the picture's middle tone on it: order 0.99
  for every choice; the light and dark of the picture keep their order. A red that is light does not exist on this scale: its reds are dark (L* 40).

Operator's answers (2026-10-22): cleaning always; the preview says where a mode is measured; the main colour both by a click on the scale and by
lighter/darker, per part now. Then: "Мне нужно не общий цвет менять ... отдельно разукрасить губы ... очки ... как в разукрашке ... на разные темы ... может даже
рандомально ... выделить некие объекты на фотографии и их понять, что это за объекты. И каждый объект выделять каким-то промежутком цветовой гаммы, которая
определяет, какая мощность будет ... и вот эти все оттенки вокруг, они тоже будут подбираться" - the main colour is per object, not for the whole picture. And, with
a screenshot of the grey-scale plate on «Big Plate 150»: "должно работать для титана любого размера"; answers: every Grade 5 plate is one titanium (batch, size and
thickness do not matter), everywhere (scales, photo works, preview, vector palette, colour map).

#### 0.20.3: the cleaning layer; one titanium per grade; the preview finds the file's titanium
- [x] E1. A picture's LightBurn file cleans first: C00 the laser's cleaning recipe (`plans.clean_layer`) over the picture's rectangle, run first; the picture on C01.
      The same for «Картинка на шкале». The time of the work includes the cleaning (scan pieces counted as the file's). Tests: the file's layers and order; the
      time shown equals the file's; an upload of the work's photograph takes C00 for the cleaning and measures C01.
- [x] G1. One titanium per grade: measurements, scales, curves, palettes and knowledge of a plate serve every plate of the same grade (a material without a grade
      is its own titanium). Map of every place that partitions by `material_id` (subagent), one helper that gives the plates of a titanium, every filter and
      comparison through it; render-cache keys follow. Screens that name the titanium say the grade and the plates measured. Tests: a Small Plate work predicts
      from a Big Plate scale; a plate of another grade stays apart; a material without a grade stays apart.
      Map (subagent, 2026-10-22) and design:
      - The rule exists: `palette._same_material` (DEC-088, the vector palette only): the same family and grade, case and spacing aside; no grade = only itself.
        It moves to `setup` as `titanium_key` / `same_titanium` and serves every place below. The titanium of a record is its current record (as the palette),
        not the grade copied into an engraving when it was uploaded.
      - Scales, curves, the preview, photo works (`prediction_store.collect`, `scale_modes`, `measured_on`; `photo_work.measured_scale`, `engravings`): the points of
        every plate of the titanium; one scale per titanium (named by the first plate it was measured on, or by the titanium asked for); a scale says the titanium
        and the plates it was measured on; an engraving on another plate of the work's titanium is the work's scale. Stored works keep their plate record.
      - Colour map: recipes measured on several plates of one titanium are one recipe (confidence over all their engravings); the «Материал» filter offers titanium
        (grade), the point still names its plate. Recipe groups keep `ti:<plate>` so palette entry ids (kept by vector works' assignments) do not change: the
        pooling is a second key (`recipe`).
      - Not changed: knowledge entries (`observation_key` `|ti:id:N` is stored: 549 entries, 500 on Big Plate, 49 on Small Plate, one recipe on both), findings,
        designer proposals, application guide, research sessions - stored keys; the operator's scope ("везде") named scales, works, preview, palette, colour map.
- [x] F1. «Предпросмотр фотогравировки»: when the chosen laser, lens and titanium have no measurement of the file's mode, it says where the mode is measured with a
      button to switch («Показать на нём»; dot modes are not searched); a photo work's file opens in the preview from the work («Файл в предпросмотре») with its
      titanium, laser and lens set.
- [x] G2. README, MarkView (REQ/DEC: one titanium per grade; the cleaning in a picture's file), walk on a copy, full suite, release 0.20.3.

#### Review of 0.20.3 (2026-10-22)
- MarkView: REQ-069 / DEC-110 (one titanium per grade), REQ-070 / DEC-111 (the cleaning in a picture's file, the work's file in the preview).
- Full suite with 12 workers: 1662 passed, nothing skipped. One new assertion (`others == 1`) depended on the order of the tests (the module's
  plate world keeps the other tests' works); it now asks for at least one.
- Walk on a copy of the live data (sqlite backup API, server on 8768; the live app on 8765 only read):
  - The operator's file «Inna Portrait-P1-17.lbrn2» (no cleaning, made by 0.20.2) on «Small Plate»: predicted (16 powers, chart-corrected), as on «Big Plate 150».
  - Work 35: the time says «из них чистка ≈ 3 мин 24 с», the file text names C00 CLEAN-CROSSHATCH-…; scale cards say «Титан Grade 5 · измерена на
    Big Plate 150». «Файл в предпросмотре» opened the preview with the work's file (C01, Min 1, Max 17), Big Plate 150, the laser and lens, predicted;
    switching to «Small Plate» predicted too.
  - At 1372 px the new button squeezed «Отменить» / «Повторить» into a column: the pair is kept on one line and the work's name narrows (also at 1200 px).
  - Colour map: the «Материал» filter offers «Grade 5» only; «Test Plate 1mm» points, uploaded when the record said «Garde 2», are Grade 5 (the record now).
  - Vector work 22: its palette of 553 entries has the same ids and colours as on the live app.

### After 0.20.3: a new work asks which kind of engraving, each kind shown on the picture (operator, 2026-10-22; plan to approve)
Operator: "Я открыл существующую Boris3 работу, и там ничего не поменялось ... где вот это изменение, которое я тебе давно просил, что когда ты открываешь
новую работу по фотогравировке, он тебе выдает вопросы, то есть какую конкретно ты хочешь делать гравировку. То есть тональную гравировку ... grayscale или какую-то
другую. И все, мы должны показывать, как эта каждая работа будет выглядеть в превью."
Evidence:
- The first goal (2026-10-21) named it: "Учти, что есть очень много разных типов фотогравировки ... один из видов ... grayscale". Built: the catalogue of kinds
  (`photo_modes`, 11 LightBurn modes), the dot kinds predicted from a photograph of the same kind (none exists), and photo works in grayscale only. A new work never
  asks for the kind; nothing shows the picture in another kind. Not said in any release report.
- Boris - 3 (live, GET only): 0.20.3 changed its file (C00 cleaning), its time (47 min incl. cleaning 3 min 24 s), the scale cards («Титан Grade 5 · измерена на
  Big Plate 150») and «Файл в предпросмотре»; its picture is the same, as every scale was measured on Big Plate 150 only (pooling adds no points). The object
  colouring is a prototype only (page «Тональность»), not in the app.
- A dot kind fires every dot at the layer's one power; the colour of a struck spot at that power and the scale's settings is the scale's colour at that power,
  between dots the cleaned titanium (its nominal colour is known). So every dot kind can be shown from the measured scales before it is engraved - as an estimate:
  single dots are the shortest rows there are, and DEC-107 shows the colour moves with row length.

Operator's answers (2026-10-22): both in one release (kinds and colouring by objects, 0.21.0); every kind that colours titanium; dot kinds shown as an estimate
from the scale until engraved. The LightBurn files of the operator: a dot layer fires at maxPower (minPower ignored), `dotWidth` / `useDotCorrection` with it
(deploma.lbrn2: jarvis and sketch at 30 %, dot width 0.02 mm, 1100 dpi).
Build order: pure modules in parallel (subagents: `dots.py` - the dots of each kind and the share they strike; `objects.py` - the objects of a picture), the work's
kind, power, preview, file and chooser meanwhile; then the colouring by objects on top.

#### Plan: kinds of photo engraving in a work (0.21.0, approved)
- [x] K1. «Новая работа» asks «Какая гравировка?» after the picture: one tile per kind that colours titanium - Градации серого (multi-colour, measured), Джарвис,
      Стаки, Аткинсон, Флойд-Стейнберг, Упорядоченный, Полутон, Газетный, Порог, Эскиз (3D-срез left out: relief, not colour). Each tile is the operator's picture
      as it would come out: grayscale from the scale as now; a dot kind by its dots (error diffusion with the published kernels, ordered by a Bayer matrix, halftone
      and newsprint by cells), each dot in the scale's colour at the dot power, cleaned titanium between, seen at a distance (and the dots at 1:1 on zoom). A dot
      kind not photographed yet says «оценка: этот вид ещё не гравировался».
- [x] K2. A work keeps its kind; «Вид гравировки» in the work switches it (undo/redo). A dot kind has one power instead of Min/Max: chosen by a click on the scale
      strip (the colour of the dots) or the field; dot width correction as LightBurn has it.
- [x] K3. The file: the Image layer in that kind (`ditherMode`, power, dpi), C00 cleaning first; the time per kind. LightBurn dithers by its own code: the preview
      uses the published algorithms and says so.
- [x] K4. Experiments confirm: «Проба этого вида» - a grey ramp in the work's kind at its power (as «Проба на ширине работы»); its photograph is measured in that
      kind (the existing dot-kind profile) and replaces the estimate; the work's engravings in that kind check it as grayscale ones do.
- [x] K5. Tests (each kind's dots, colour of a dot kind from a scale, the file's ditherMode, the dialog), README, MarkView REQ/DEC, walk on a copy, release.

#### 0.21.0: colouring by objects ("как в разукрашке"), in the same release as the kinds
- [x] T1. Objects of the picture: the people model's parts, the lips and eyes from the face detector (lips refined by their colour inside the mouth's ellipse), the
      glasses and other things worn, and the background split into its own objects (pole, sky ...) by region segmentation (OpenCV contrib, already a dependency);
      the AI may name them. Prototype on «Inna Portrait» first and show the operator before building.
- [x] T2. Each object gets its own stretch of the scale: a main colour (a click on the scale strip) and lighter/darker; the path through it stays in its colour
      family (steps of at most 5 dE, lightness never rising) and the object's own light and dark tones are laid around it (its middle tone on the main colour).
      «Авто» is 0.20.2 for the whole picture.
- [x] T3. Themes: ready palettes over the scale's families (warm, cool, contrast ...), «Случайно», and the AI's theme from a wish ("очки красные, фон синий").
- [x] T4. Kept in the work, undo, the picture key, the file; tests; UI; README; MarkView; walk; release.

#### Review of 0.21.0 (2026-10-22)
- Built: K1-K4 and T1-T4 (REQ-071, REQ-072, DEC-112, DEC-113). Pure modules `dots.py` (each kind's dots), `objects.py` (the objects), `colouring.py` (a path through each
  object's main colour, themes); the work keeps `kind`, `dot_power`, `colouring`, `ai_theme` with undo; endpoints `/kinds`, `/kinds/{kind}.png`, `/closeup.png`,
  `/objects`, `/objects.png`, `/theme`, `/ai-theme`; UI «Какая гравировка?», «Вид», the dot power on the strip, the «Раскраска» tab.
- Not built: K2's dot width correction (`dotWidth` / `useDotCorrection` are not written); K4's check of a dot-kind work's engravings has no test of its own (they go
  through the general path of other settings). The background pieces follow the segmentation at 400 px and their borders can be stepped.
- Walk on a copy of the operator's data (walk-0210, port 8769): Inna Portrait - lips by a click (12.11 %), «Тёплая», «Случайно», undo back to «Тёплая», a real AI theme
  («очки золотом, фон синий, губы красные, кожа светлая») answered at the first attempt, the file C00 + C01 with 216 greys, «Какая гравировка?» with ten tiles,
  Джарвис at 14.6 % with the «Раскраска» tab saying it is grayscale only; no console errors.

#### 0.20.0, vector works: the size of each layer (and the photo colours added to their palette)
Map (subagent, 2026-10-22): a vector work's colour is one palette entry per recipe (`palette._entry` = `colormap.agreed`), test-plate patches and works pooled with no size;
the preview paints every region of a layer with its entry's colour (`vector-editor.js paint`, `vector_job._draw_thumbnail`); the export is one layer per colour, each region a
separate shape, no fill grouping written (LightBurn's default applies; assumed "all shapes of the layer at once" - to confirm with the operator's LightBurn); patch sizes are
reachable through plan layers / plate cells / the stored LightBurn files. The engraved vector works on file (102-104) used a palette of another titanium, so they cannot show
the size effect; it has to be measured.
- [x] W1. Each fill observation gets its row span (a plate patch: its width; a work's layer: the span of the layer's shapes along a row), derived as in S1.
- [x] W2. A palette entry's colour at a row span (as S2); the work computes each layer's row span from its shapes once the colours are assigned, re-predicts the layer's colour at
      that span, and the preview, the thumbnail, dE to the wanted colour and the promised colours of the check use it. The automatic colour choice runs again on the
      re-predicted colours (two rounds), so a layer is chosen for the colour it gives at its own size.
- [x] W3. A fill size plate: the same settings as patches 5 / 20 / 50 / 100 mm wide, to measure the shift for fills; until then a layer outside the measured sizes is marked.
- [ ] W5. Colour works («Цветная гравировка», `conversion`, validated knowledge entries): the same sizes - an entry's colour at the row length of each source colour's
      rects. Not in 0.20.0: the operator has made none (2026-10-22: no plan of that mode); to ask in the report whether it is wanted.
- As built (2026-10-22): S1 derives the row length from the pair's stored LightBurn file for every point, new and old (`row_length`, nothing recorded in the report or the
  database); S2 without a size takes the size most engravings measured, not all points; `others` of an engraving's check counts the engravings the prediction used (at its
  size), not every one of the mode. W2 needs no second round: each source colour is compared with each entry at the row length of its own regions (`palette.assign`
  `size_of`), and the shown colours use each layer's actual regions; row lengths are taken on the split as made (smoothing moves borders by far less than 10 %). S5/W3
  (plates) were built by a subagent on its own branch and merged; S6 makes one ramp of the work's width at its scale, Min and Max, refused when the laser has another lens.
- [x] W4. Tests and the walk on a copy go with S7; one README section, MarkView REQ/DEC and one release for S and W. The planned "photo-engraving colours in the vector
      palette" comes with sizes from the start.
Former plans move: photo-engraving colours in the vector palette (G) -> 0.21.0, every section on one screen (H) -> 0.22.0.

#### Review of 0.20.0 (2026-10-22)
- Full suite with 12 workers, nothing skipped. One test (`others == 2`) depended on the order of the tests: `others` counted the engravings of every size, which also made
  the work's text wrong; it now counts the engravings the prediction used. The ramp test accepted "outside" only; with another test's ramp in the same store the work's
  width can lie between two sizes, so either is accepted before the ramp is measured.
- Walk on a copy of the live data (sqlite backup API, server on 8768, the operator's app on 8765 only read):
  - Work 33 «Inna Portrait», 100 mm: the pill «100 мм: между измерениями 38,4 и 150 мм», the paragraph on sizes and «Проба на ширине работы» in «Картинка». The note
    "100 % of the picture lies at powers only one engraving measured" was misleading between two sizes (each size has one engraving, the colour is interpolated, not
    repeated): it is left out when the size is between; the size's own note says how the colour was taken.
  - «Проба на ширине работы» made plate 34 (one ramp 100 x 4 mm at the work's scale, Min 1, Max 30, markers) and opened it. While the walk ran, someone clicked in the
    walk tab and changed the copy's scale of work 33 to 250 ns (audit 671-678 on the copy); the ramp took that scale, as it should. The live work is unchanged (350 ns).
  - Vector work 22: all 27 layers "outside" (patches 3.8-29.6 mm, layers 5-44 mm). The full sentence per layer pushed the area and time out of the narrow panel and the
    explanation took half of it: each layer now shows «↔ 13.3 мм» (warning colour when not measured at that length, the full sentence as a tooltip) and the explanation
    is folded under «27 из 27 слоёв: цвет при длине их строк (↔) не измерен».
  - Plate dialog: «Размер заливки» with its explanation and a 150 mm default size.
- The 150 mm engraving (pair 111 of plan 32 «Inna Portrait-P1-30», restored from its file; work 28 of the plan no longer exists) cannot be reproduced under
  leave-one-out: it is the only measurement of its mode at 150 mm, so its check says "other size, measured at 38.4 mm" (nothing to compare with), not a failure. With
  it included, the 150 mm scale is that engraving itself.

## 0.21.1: «Новая работа» asks «Какая гравировка?» as its own step (operator, 2026-10-22)
Operator: "Почему при фотографировке, когда я выбираю новую работу, он не спрашивает меня, какую фотографировку я хочу сделать?" In 0.21.0 the dialog asked for the
picture, name and width only; the question opened after «Создать» (verified on a copy: it does open, with the picture in every kind). Answer: «Шаг 1 картинка, шаг 2 вид».
- [x] N1. One dialog, two steps: «Новая работа · шаг 1 из 2: картинка» (picture, name, width; «Дальше →» uploads it and makes the work) and «шаг 2 из 2: какая
      гравировка?» (the tiles of the kinds with the operator's picture, grayscale chosen; a click chooses; «Создать в «…»» sets the kind and opens the work).
      «← Назад» returns to step 1 with its fields kept, and the work made by «Дальше» is deleted; closing the dialog at step 2 deletes it too.
- [x] N2. The tiles' grid is shared by the new-work step and the «Вид» chooser in a work; the work no longer asks on `&ask=kind` (no new work goes there).
- [x] N3. UI tests (both steps, «Назад», closing, the scales page's «Новая работа»), README 0.21.1, a MarkView bug, walk from «Мои работы» → «Новая работа» on a
      copy, full suite, backup, deploy, commit and push.

#### Review of 0.21.1 (2026-10-22)
- N1, N2 built: `newWork` is two modals in sequence (step 1 builds its fields once, so «Назад» shows them as they were); `kindTiles` is the
  grid shared with the work's «Вид» chooser; `modal()` got an optional `onClose`, called once however the dialog closes, which deletes the
  draft work unless «Создать» was pressed. `workScreen` lost `ask`, the route lost `&ask=kind`.
- Tests: the list test walks both steps and creates in «Джарвис»; a new test checks «Назад» (fields kept, the draft deleted) and Escape;
  the scales page's test goes through both steps; the kinds test opens the chooser from «Вид» of a work. UI tests 17 passed.
- Walk on a copy of the live data from «Мои работы» → «Новая работа», click by click: step 1, step 2 with all 10 kinds pictured,
  «Назад» kept the fields and deleted the draft, «Создать в «Джарвис»» opened the work in Джарвис at 29,1 %, Escape on step 2 deleted
  its draft; no console errors.
- Known: a work created in a dot kind has one undo step (back to grayscale), as the kind is set right after the work is made.

## 0.22.0: photo engraving inside a vector work, «фото-зоны» (operator goal, 2026-10-22)
Operator (voice): "в векторной работе ... выделял ... все, которые на голове ... врезал бы эти вектора и вставлял бы вместо них картинки из
фотогравировки ... часть картины это просто вектора, а часть фотогравировка ... выбирать, какую фотогравировку, то есть какую палитру ...
простые конструкции, чтобы можно было быстро поменять ... Jarvis, а можно сделать и цветной в плане Grayscale ... лицо это чисто
фотогравировка, причем сконфигурируемая так, чтобы было удачно и удобно видеть и подходило к общей картине".
What exists (mapped 2026-10-22): the photo work's kinds (grayscale + 9 dot/edge kinds, `photo_modes`, `dots`), its scales (`prediction_store`:
curve at a width, Min/Max, colours chosen by the picture keeping the drawing, dot look estimated from the scale), the Image-layer writer
(`plans._image_setting`, `_bitmap`, `export_picture`); the vector editor selects regions by click / Shift+click only (drag pans), has
«Не гравировать» and merges, undo/redo of the whole colouring (DEC-077). Nothing puts an Image layer into a vector work's file; the photo
file writes transparent pixels white (= Min power in grayscale), which over vector areas would engrave them.
Live data: work 22 «Inna + Boris» has 27 of 28 layers (one zone fits), 10 grayscale scales on laser 1 / lens 2 / Grade 5.

Decisions taken with defaults (to confirm with the operator in the report):
- A photo zone = regions of the split + its own photo engraving (kind, scale, Min/Max or dot power, «цвета по картинке»), kept in the work's
  colouring: undo/redo, copy and history carry it; restoring a colour variant keeps the zones as they are now.
- In the file each zone is one Image layer after the colour layers: the work's picture cut to the zone's box, transparent (alpha 0) outside
  the zone, never white, as the operator's own mixed works cut vector areas out of a picture (DEC-095). Cleaning C00 covers it as before.
- The vector file is MirrorY=True (top-down): its pictures are stored top row first (LightBurn shows row 0 at the smallest y).
- A new zone takes the best measured scale of the work's laser, lens and titanium (chart first, then engravings), its measured span at the
  zone's width (DEC-107: rows as long as the zone is wide), grayscale, colours chosen by the picture keeping the drawing.

Order (the operator's ask first):
- [x] Z1. Server: zones in the colouring; ops `photo_add` (new zone or into one), `photo_remove`, `photo_set`, `photo_delete` through
      `/colouring` (undo, history); zone regions leave the colour layers; merges, a new split (zones carried over by area) and variants keep
      them consistent; the view lists the zones; the file's layer cap counts them; `POST /vector/{id}/lasso` (regions at least half inside).
- [x] Z2. The zone's picture: crop + mask from the same smoothed borders as the paths; predicted look per kind (grayscale on the scale with
      Min/Max and colours by the picture; dot kinds estimated from the scale or from their measured tones); `photo/{zone}.png` (transparent
      outside), `photo/{zone}/kinds` + tiles; render cache keys with the scale's points; RENDER_VERSION bump; the list thumbnail shows zones.
- [x] Z3. LightBurn file: an Image layer per zone (ditherMode, Min/Max or Min=Max=dot power, the scale's settings), bitmap with alpha at
      <= layer dpi placed on the zone's box; time of each zone (its area and scan pieces); the export records the zones.
- [x] Z4. Editor UI: lasso in «Выделение» (drag draws; Shift adds, Alt removes; Space+drag or the middle button pans); selection actions
      «Фотогравировка» / «В зону N» / «Вернуть в вектор»; a tab «Фото» with every zone: the kind as tiles of that zone, the scale (bars),
      Min/Max or the dots' power, «Цвета по картинке», select / dissolve; the stage shows each zone's predicted picture in its regions.
- [x] Z5. Tests (state, ops, undo, merge, resplit, lasso, export read back by our reader: picture on the zone, transparent outside, after a
      LightBurn 2.2 save too; API; UI in node), README, MarkView REQ + DEC, version 0.22.0, full suite, backup, deploy, walk on a copy of
      work 22 from «Векторная работа» → the work, timings of every new request, the operator's app checked view-only.

#### Review of 0.22.0 (2026-10-22)
- Built as planned (Z1-Z5); additions found while building: the brush on a zone's region (scope «Участок» or «Заливка похожих») gives it a colour and
  takes it out of the zone, «Весь исходный цвет» leaves zones alone, a fill of similar colours stops at a zone, «Не гравировать» takes the region out of
  its zone; a copy of the work keeps its zones (tested). The scale choice is a list of scale cards with their colour bars, not a select (the select cut
  its text at the panel's width).
- Walk on a copy of the live data (`sqlite3 .backup` + files cloned, 192 rows of paths rewritten, none left; dev server on 8791 in a tab named «ТЕСТ: копия
  данных, порт 8791 (не настоящее приложение)», stopped after): «Векторная работа» → «Inna + Boris» → «Выделение» → lasso around the left face (108
  regions) → «Сделать фотозоной» → C28, 26 colour layers + 1 zone of 28 → «Фото»: tiles, scale cards, a warmer scale, Jarvis at 20 % → the file: image
  layer «C28 Photo 1 jarvis P20», Min = Max = 20, 49.95 x 63.9 mm.
- Found by the walk and fixed:
  - `showZones` called `.map` on a NodeList: the editor threw on every load (and skipped `showImage`). The node DOM of the UI tests returns arrays, so
    no test saw it; `test_no_ui_script_uses_a_node_list_as_an_array` now checks every UI script.
  - Slow: each tile recomputed the zone's scale curve and dots (0.3 s, ten tiles), «kinds» scanned all measurements once per kind (0.75 s), the list of
    scales took 1.6 s. `prediction_store.collect` is now kept per state of the data (`Store.stamp()`: rows written through the store and commits by any
    other connection), kinds never photographed are skipped (`photographed_kinds`), and a tile's key holds only the settings its kind draws from. After:
    tile 0.05 s, kinds 0.08 s warm / 0.15-0.25 s after a change, scales 0.75 s first / 0.05 s.
  - The header and the «Файл» tab counted colour layers only; a zone's time row in «Файл» was labelled «Чистка». The «Слои» rows cut their details
    with «…» at 1771 and 1372 px (since 0.9.0): the details are on their own line now. A changed zone picture blanked the zone until it loaded (now swapped
    when loaded); the «Фото» tab jumped to the top on every change (now replaced in one step, the open list of scales stays open).
- Not changed: any edit of work 22 takes about 1.3 s (0.56 s the operation, mostly the colour state's palette at size; 0.6 s the view it returns) - as
  before 0.22.0; a zone adds up to 0.2 s. A cold first view of work 22 takes 5-6 s (as before).
- No RENDER_VERSION bump: no existing drawing changed under an unchanged key (the thumbnail's key now holds the zones' picture keys).

- Released 2026-10-22: full suite 1794 passed (-n 12, 2 min 46 s, none skipped); backup `backups/titanium-before-0.22.0-20261022T202212Z.sqlite`
  (integrity ok, 91 pairs - latest 111, 2121 observations, 10 plans, audit 806); wheel installed with its dependencies, every declared library imports;
  8765 restarted on 0.22.0 and checked with GETs only: header v0.22.0, work 22 with no zones and 27 layers, the «Фото» tab's empty state, no console
  messages, audit still 806. DEC-114 and DEC-115 accepted.

## 0.22.1: a selection and a photo zone are outlined as one shape (operator, 2026-10-22)
Operator, after 0.22.0: «Я пытаюсь объединить какие-то секции, но я не вижу их нормально, не могу перевести фото.» Their open tab was still
0.21.1 (no «Фото», no lasso) - reloaded (no unsaved state: audit unchanged since the deploy). Then: «Если мы переводим фото, то пусть он все
выделения как-то обозначает, там желтым или еще чем-нибудь, ну рамки. Пусть он это обозначает общее, причем не каждую часть, а общее. То есть
когда он соединяет ближайшие, что он должен объединять его одно.»
Now each selected region gets its own yellow line (108 outlines for a face), thin and lost on the cream colours.
- [x] O1. `segment.to_svg(..., borders=True)` (the editor's `split.svg` only): a hidden `<g class="vw-borders">` with every border arc once as
      its own path (the same curves the regions use) and `data-sides` = the regions whose loops use it.
- [x] O2. Editor: the outline of a set of regions = the arcs with a region of the set on one side only, one path; drawn above the regions with
      a dark halo under the line. Selection - yellow; hover (zone card, layer row, the fill's reach) - white; each photo zone - dashed, while
      the «Фото» tab is open. `App.tabs` gets an optional `onSelect`. The per-region classes `vw-sel` / `vw-hot` go.
- [x] O3. Tests (python: borders in the SVG; node: the outline of two neighbours skips their shared border, zone frames only on «Фото»),
      README 0.22.1, version, suite, walk on a copy (work 22, lasso on the face), backup, deploy, the operator's tab reloaded.

#### Review of 0.22.1 (2026-10-22)
- Built as planned. The split SVG of the editor carries every border once (`<g class="vw-borders" display="none">`, `data-sides` from the regions'
  loops); the editor reads them as data and removes the group. `drawLine(kind, groups)` sets one halo + one line per kind (zones, hover, selection,
  in that order above the regions) with `data-regions` naming what it outlines; the per-region classes `vw-sel` / `vw-hot` are gone (`vw-far` stays:
  it marks each far region). `App.tabs` has an optional `onSelect`; the editor shows the zones' outlines (`show-zones`) while «Фото» is open.
- Tests: python - the borders outline any connected set exactly as `merge_regions` does (2, 3, 6, 12 regions; traced and smoothed), each smoothed
  border has the same curves as the regions on its sides (115 of 191 checked; single-curve loops are split); node - one outline for r1+r2 without
  their shared border, line + halo only, the zone framed only on «Фото», the zone card's hover outlines the zone as one shape.
- Walk on the copy of work 22 (port 8791, stopped after): the face zone framed as one dashed shape on «Фото»; «Выделить» -> one yellow outline of 108
  regions (1 ms), visible on the light face; hovering 27 layer rows 4 ms; no console messages. split.svg 557 -> 868 KB (1667 borders), served in 0.05 s
  first, 0.005 s after.
- Not changed: the face zone's regions are not all connected by shared borders (the editor says so), so «Слить в один контур» stays off for
  that selection, as before; «Сделать фотозоной» does not need them connected.

- Released 2026-10-22: full suite 1797 passed (-n 12, 2 min 42 s, none skipped); backup `backups/titanium-before-0.22.1-20261022T204119Z.sqlite`
  (integrity ok, 91 pairs - latest 111, 2121 observations, 10 plans, audit 806); wheel installed with its dependencies, imports ok; 8765 on 0.22.1
  (split.svg 868 KB in 0.05 s, view 5.3 s cold as before); the operator's open tab of work 22 reloaded (it was on 0.22.0, nothing unsaved): v0.22.1,
  six outline paths, no console messages.

## 0.22.2: the engraving plan lists the photo zones (goal continued, 2026-10-22)
Found by checking every screen that lists a work's layers against the file: «План гравировки» (`#/plans/22`) listed the 26 colour layers of work 22
and not its zone's Image layer C28, though its own export writes it (`vector_job.export`).
- [x] P1. `vector_job.plan_zones(store, plan)`: the zones as the editor shows them with the file's settings, numbered after the stored colour layers;
      `GET /api/plans/{id}` returns them as `photo_zones` ([] for any other plan).
- [x] P2. `plan.js`: a row per zone after the colour layers - layer name, «Фотозона N · kind», powers and settings, «Изображение (Image), режим …»,
      the zone's picture in «Прогнозный цвет», regions; a zone that cannot be engraved shows the server's reason, translated. A work of zones only
      keeps its table and export.
- [x] P3. Tests: API (two zones, grayscale and Jarvis: names, numbers, pictures as the editor's, settings, the plan's export has them last); node
      (rows, powers, translated reason, pictures, export enabled, zones only). Walk on the copy (8791, stopped): C28 row with the face picture, 108
      regions; nothing cut at 1771 and 1372 px.

#### Review of 0.22.2 (2026-10-22)
- `GET /api/plans/22` on the copy: 0.07-0.1 s warm; 2.4 s the first time after a start - `colormap.references` parses 17 stored LightBurn files to
  find their cleaning layers (2.6 s, cached per process by path and mtime) and the smoothed geometry (0.7 s): the same cost the editor's first view
  pays (5.3 s). Not changed here; a lasting fix stores the found cleaning layer (a witness observation or a disk cache) - to propose.

- Released 2026-10-22: full suite 1800 passed (-n 12, 2 min 54 s, none skipped); backup `backups/titanium-before-0.22.2-20261022T205050Z.sqlite`
  (integrity ok, 91 pairs - latest 111, 2121 observations, 10 plans, audit 806); wheel installed with its dependencies, imports ok; 8765 on 0.22.2,
  `/api/plans/22` 0.08 s (no zone in the live work 22 yet: `photo_zones` []); the operator's tab reloaded from 0.22.1 (nothing unsaved), no console messages.

## 0.22.3: «Фото» selects, Escape drops the selection (operator, 2026-10-22)
The operator: «Не выбирается» (a screenshot of «Фото» open, the hint «Щелчок — вернуть автоматический выбор: только эта область»), then
«Когда нажимаешь Escape, выделения должны уходить.»
- [x] F1. Root cause: the tool buttons and the selection block are on «Кисть»; on «Фото» the brush stayed the tool, so a click painted «Авто» and
      a drag panned. Opening «Фото» makes «Выделение» the tool; the selection block moves to the pane that is open («Кисть» or «Фото»); «Выделить»
      of a zone stays on «Фото». The empty-zones hint says where the button is.
- [x] F2. Root cause: the editor skips every key while a field has the focus (a zone's power, a checkbox, the slider), Escape too; and Escape left a
      lasso being drawn and the white line under the pointer. Escape now drops the selection from anywhere but a dialog, cancels the lasso
      (nothing is asked) and hides the line until the pointer moves; the zone frames stay.
- [x] F3. Tests: node - «Фото» selects and holds the selection, a click there posts nothing, «Сделать фотозоной» from it; Escape from a power
      field, the hovered region and zone card line, a lasso cancelled mid-draw (and the click after it selects), a dialog keeps its Escape (fails on
      the old handler). The node test document keeps and fires its listeners now (`document.dispatch`). Walk on the copy: a click, Shift+click
      and a lasso on «Фото», a zone made from it (1.5 s), a real Escape from a power field.

- Released 2026-10-22: full suite 1802 passed (-n 12, 3 min, none skipped); backup `backups/titanium-before-0.22.3-20261022T210551Z.sqlite`
  (integrity ok, 91 pairs - latest 111, 2121 observations, 10 plans, audit 806); wheel installed with its dependencies, imports ok; 8765 on 0.22.3.


## 0.22.4: the delta E tolerance in the new vector work form (operator, 2026-10-22)
The operator: «Чини» (a screenshot of the form: «Задайте порог ΔE для этого плана: допуск для этого лазера с этой линзой не сохранён», and the
fill warning). Root cause: no rules were ever saved for any laser and lens (live and every backup), and the tolerance is never invented
(conversion._threshold, palette.tolerance_for); the form said so only after «Создать работу». The operator chose ΔE 5 and «show at once and remember».
- [x] T1. ΔE 5 saved to the rules of laser 1 + lens 2 through `PUT /api/rules` (tried on a copy first: only the setting row changes; knowledge,
      its events, findings and works do not).
- [x] T2. The form reads `/rules` for the laser and lens (and on every change of them): «из правил: 5» or a red field with the scale and
      «Запомнить для этого лазера с линзой» (on); an empty field with no rule is not sent; a typed tolerance is saved to the rules before the work.
- [x] T3. The «Титан» hint follows the strategy (photo: every plate of the grade, `palette.vector_palette`; silhouettes: this plate, `vector_job.eligible`).
- [x] T4. Tests: `tests/test_vector_form_ui.py` (no rule: asks first, nothing sent, PUT then POST with the threshold; a rule: named, never PUT;
      the hint per strategy). Walk on a copy: both lenses, the error with the focus, the rule saved for the unknown lens and the work created.
- Released 2026-10-22: full suite 1804 passed (-n 12, 2 min 38 s, none skipped); backup `backups/titanium-before-0.22.4-20261022T212248Z.sqlite`
  (integrity ok, 91 pairs - latest 111, 2121 observations, 11 plans, audit 806, the ΔE 5 rule in it); 8765 on 0.22.4.
- Seen: work 39 «Inna Portait Mix 1» (21:08, before the rule) and work 22 carry ΔE 0.05 typed into the form - every colour is out of tolerance
  and takes the nearest recipe, never a faster one; the editor's «Цвета» tab changes it (`set_threshold`). Left to the operator.

## 0.23: a photo zone does what a photo engraving work does (operator, 2026-10-22; plan approved: a zone screen, shared code)
The operator: «в фотозоне нужно иметь тот же функционал, как и в этой фотогравировке ... сохранить рисунок, подобрать серые, подцветить и так
далее ... без этого у меня какая-то хрень получается». A zone has kind, scale and powers only; its greys are fixed to «по рисунку»
(photo_zones.py:53). The photo work's «Картинка» is grey picking (по рисунку / ближайшие / по объектам) and contours (no brightness/contrast
exists); «Раскраска» is per-object colours, themes, «Случайно»; «AI» the parts' rules and an AI theme. The zone's prediction and file layer
already share prediction_store with the photo work; its state, objects, themes and AI do not.
Design (C): one shared core, no copy.
- [x] Z1. Move the photo work's state core out of photo_work.py into photo_state.py (keys and defaults, validation of a change, the
      prediction item, objects, themes, AI theme and rules); photo_work.py keeps the record (plan row, picture, width, undo). No behaviour
      change: the photo work tests pass unchanged.
- [x] Z2. A zone stores the same keys in the vector work's colouring (old zones get the defaults): grey picking, contours, colouring by objects,
      parts' rules. Its picture and its LightBurn layer follow them. Undo, copies, variants and the plan page come with the colouring.
- [ ] Z3. Objects and parts are found once on the whole picture of the vector work and cut to each zone (keys stay when the zone grows,
      after a re-split and between zones).
- [ ] Z4. (0.23.0: view, preview, close-up, settings, undo, redo; 0.23.1: the rest) Zone routes under /api/vector/{id}/photo/{n}: view, prediction side by side, dot close-up, objects, parts, settings (= photo_set,
      one editor undo step), theme, AI theme, AI (reads the work again after the AI answers).
- [x] Z5. photo-panels.js: «Картинка», «Раскраска», «AI», «Шкала», kinds and dots panels out of photo-engraving.js, taking a base URL; the
      photo engraving screen uses them (its tests unchanged in behaviour).
- [x] Z6. «Открыть» on a zone card: the zone in the photo engraving layout (scales left, picture and prediction in the middle, the tabs right,
      «← К работе»); Ctrl+Z/Ctrl+Shift+Z are the vector work's.
- [x] Z7. The plan page and the editor's zone card name the new settings; DEC-116 (extends DEC-114).
Review of 0.23.0 (Z1, Z2, Z4 in part, Z5, Z6, Z7): photo_state.py holds the state core of both; photo_zones.full() reads a zone made before
as the drawing kept (zones() still returns the stored dicts: the merge mutates them). photo-panels.js holds scales, «Картинка» (options
ramp, original, width, objects, layer), «Раскраска», «AI» and the kinds; vector-zone.js is the zone's screen (#/vector-zone?work=&zone=),
its «Подтверждение» is the scale's own (no engravings of the zone yet). «Раскраска по объектам» is not offered on a zone until its tab
comes (0.23.1). Tests: test_vector_photo_zones (API), test_vector_zone_ui (screen), test_vector_editor_ui («Открыть»),
test_plan_screen_ui (the greys named).
0.23.0 deployed 2026-10-22 22:14 UTC (backup titanium-before-0.23.0-20261022T221427Z.sqlite). Walk on a copy (work 39, zone 1, 175
regions): «Открыть» 0.41 s, tiles of «Вид» 0.2 s (images 0.43 s), no cut text at 1771 and 1372 px on every tab; undo/redo/Ctrl+Z
right. Defect, not new: a change takes 0.8-1.1 s = the editor's colour() 0.74 s (_state's nearest delta E over 553 entries x 25
colours with sRGB each 0.42 s, vector_palette rebuilt each op 0.29 s) + the zone view 0.3 s; a photo work's change takes 0.6 s.
Proposal (needs the operator's approval: it is the editor's core): keep the palette per data version, compute the nearest delta E
on L*a*b* only, draw the zone's look once per key.
Out: «Подтверждение» (engravings belong to the vector work) and the width (a zone's width is its box). Releases: 0.23.0 = Z1, Z2, Z4, Z5, Z6
with «Картинка», «Шкала», kinds, dots; 0.23.1 = Z3 and «Раскраска» + «AI». Each with node and API tests, a walk on a copy, timings.

## 0.24: every accepted photo engraving makes the next prediction better (operator, 2026-10-23; all four parts approved)
The operator on «Inna Portrait-P1-30 150»: the prediction shown before engraving was much darker than the result, the yellows were
missed; after accepting results the platform must rework its colours and settings so the next prediction is closer.
Findings (mode 150 mm/s · 60 kHz · 350 ns · 0.0212 mm, three measurements): 38.4 mm grey ramps on Big Plate 150 (3 mm, pair 108),
a 100 mm portrait on Small Plate (2 mm, no cleaning, pair 109), a 150 mm portrait on Big Plate 150 (cleaned, pair 111). Before 111
the prediction at 150 mm took the nearest size, 109: median 18.7 dE, 2 of 16 tones within 5. Causes: (1) row length (DEC-107) — at
150 mm 5.5-14.6 % gives straw and gold, at 38.4/100 mm brown, violet, blue; no power shift or affine power map carries one size to the
other (best leaves median 10 dE); (2) another plate — the scale pools every plate of the grade (DEC-110), thickness and cleaning not
weighed; (3) the photograph — clean titanium of the same plate and cleaning reads L* 79.4 on the ramp photo and ~91 on the portrait's
(its Min tone over the cleaning); chart-corrected photos are taken as absolute (DEC-056) and never aligned. Witnesses of other
chart photos: 79.3, 79.0, 79.4, 71.7.
Order: the review first (it is also the measure), then each change of the model is kept only if it lowers the reviews' errors.
- [x] R1. 0.24.0 «Прогноз и результат» (review of an acceptance): for each tonal layer of an accepted pair, the curve of its mode from
      the engravings accepted BEFORE it at its own row length (curve_at, nearest size included, said so), per tone predicted vs
      measured (swatches), median/max dE, share within the tolerance, lighter/darker and yellower/bluer on average; causes with their
      numbers: size outside or between the measured ones, the prediction made on other plates (name, thickness), cleaning differing,
      the photograph's clean titanium vs the nominal. GET /api/pairs/{id}/review; a card in the experiment's «Результат»; a summary of
      every review (GET /api/reviews: median dE over all) as the baseline. DEC-117.
- [ ] R2. 0.24.2 Photo alignment: a chart-corrected photo whose clean titanium is measured (the witness, or the Min tone of a grayscale
      image over a cleaning layer) has its colours brought to the nominal clean titanium in linear light (as camera-relative photos
      already are, DEC-056), for the grey scales and the review; the vector palette left as it is until the operator says (it would move
      validated recipes). Kept only if the reviews' median dE drops. DEC-118.
- [ ] R3. 0.24.3 Own plate: a scale curve takes the points of the work's own plate when it has any, then the same thickness, other
      plates of the grade only when none, and says so. Kept only if the reviews' median dE drops. DEC-119.
- [ ] R4. 0.24.4 Trust in a prediction: the photo work and the zone screen say the expected error of their prediction from the reviews
      of the same situation (size measured / between / outside; own plate / other) and, outside or on another plate, offer
      «Проба на ширине работы».
Then: the zone's «Раскраска» and «AI» (planned as 0.23.1) as 0.25.0; the change latency proposal still waits for the operator.
R1 review (0.24.0, built): prediction_review.py (review, summary cached per data state), GET /api/pairs/{id}/prediction-review and
/api/prediction-reviews, the card in the experiment's «Результат» (prediction-review.js). On a copy of the operator's data: pair 111 median 18.7 dE,
max 59.5, 13 % within 5, lighter by 17.1 L*; size outside (38.4; 100 mm, took 100), Small Plate 2 mm vs Big Plate 150 3 mm, no cleaning vs
cleaning, clean titanium 91.2 vs 76.2 (prediction's photo) and 79.4 (same plate and cleaning: the photograph's light). Baseline: 3 layers
(88, 109, 111), median 13.8 dE over 47 tones; 10.2 where the size was measured beforehand (88 vs 93: same plate and cleaning, its photograph
9.2 L* lighter). Cold first call 1.8 s (colour references, once per process), then 0.03 s; the card loads after the rest of the tab.
0.24.1 (bug, operator 2026-10-23 «Я расставил углы но все равно не нашел картинку», «Мне кажется он не правильно углы подставляет»):
pair 113 (grey scales TCE-1C844F67 on Test Plate 1mm, IMG_3385): no marker visible, automatic alignment found 0 of 3; the manual corners
reached the server squeezed in x (right corners 0.785 instead of 0.985): the corner frame (.photo) stretched to the review's flex column
(1268 px) while the photograph stayed 1052 px. Fixed with width:fit-content; on a copy the corners at the cleaning's edges put all 9
ramps in place (offsets 0-15 px). No accepted pair used manual corners (only 24, deleted, and 113, not accepted).

## 0.25: the dots of a dot kind take any colour picked on the colour map (operator, 2026-10-23; plan approved: only recipes at a dot step, 0.0085 mm or more)
The operator: «для таких вот вещей, как Jarvis и другие, у нас не получается выбрать цвет точки… перекидывало на карту цветов, и я
там оттуда выбирал цвет… Я так бы мог выбрать любой бы цвет». Now a dot kind fires every dot at one power of the work's grey scale
(`dot_power`, the slider and the strip of «Точки, %»), so the dots can only be the colours of that scale (work 37 «Inna Portrait 2»,
Аткинсон: 150 mm/s · 60 kHz · 250 ns · 0.0212 mm, 1..30 %). A dot kind's layer is one set of settings (Min = Max), so any measured
recipe can be its dots: its power, speed, frequency, Q-pulse, step and passes, the step being the dots' pitch (DPI = 25.4 / step).
On a copy of the operator's data: 573 fill colours of this laser, lens and grade (Scan, 169 at 0.002 mm, 153 at 0.003, 120 at 0.0169, ...),
153 of them at a step of 0.0085 mm or more (yellows, golds, greys, a few magenta, violet, blue, red); 348 grey-scale tones (Image).
What the estimate is: the map's colour is a solid fill's; the dots are shown as now (the recipe's colour at the work's width,
`palette.at_size`, DEC-107, mixed with the cleaned titanium in the share the dots strike) until «Проба этого вида» at those settings
measures them. At a fine step (0.001-0.005 mm, 5080-25400 dpi) the dots overlap many times and the fill's colour says little about them.
- [x] D1. State: `dot_recipe` in `photo_state` (None: the dots on the work's scale at `dot_power`, as now; else the id of an entry of
      `palette.vector_palette` of the work's laser, lens and titanium grade, DEC-088 ids, with a copy of its settings and colour when
      chosen). Kept in undo/redo. Choosing a power on the scale (slider, strip) or another scale returns the dots to the scale.
      A recipe no longer in the palette: the work says so and keeps the choice; the file waits for another colour.
- [x] D2. Dots from a recipe: the look, the close-up, the time and the LightBurn file use the recipe's settings (Image layer in the
      kind, Min = Max = its power, its step as the layer's DPI); «Проба этого вида» engraves the ramp at those settings and its
      photograph replaces the estimate (`_measured_dots` at the recipe's mode).
- [x] D3. A grey-scale tone picked on the map: the work goes to that measured scale and its dots to that power (the existing settings
      change), so every point of the map of this laser, lens and grade can be the dots' colour.
- [x] D4. API: GET /api/photo-works/{id}/dot-colours (which points of the map can be the dots and, for the others, why: another laser or
      lens, another grade, a line, not accepted yet, a step finer than the dots allow); POST settings with `dot_colour` (a point of the
      map); the view says where the dots' colour comes from.
- [x] D5. UI: in the work's «Точки» a line «Цвет точек: <swatch> со шкалы работы, 11,3 %» or «с карты цветов: <settings>», buttons
      «Выбрать на карте цветов» and «Вернуть точки на шкалу». The map in a picking mode (#/colors?dots=<work>): a strip on top names the
      work and its kind and leads back; the laser and lens filter set to the work's; a picked point or a found recipe shows «Точки этим
      цветом» (or why it cannot be) and returns to the work with it.
- [ ] D6. The same for a photo zone of a vector work (its zone screen), on the shared code, as 0.25.1.
- [x] D7. Tests (state, file, API, node UI of both screens), a walk on a copy (8791) with timings and cut text at 1771/1372, README,
      REQ and DEC through markview, SemVer 0.25.0.
Then R2-R4 of 0.24 move to 0.25.2-0.25.4 and the zone's «Раскраска» and «AI» to 0.26.0.

### 0.25.0 review (2026-10-23)
- Built as planned (REQ-074, DEC-118), with these departures from the plan:
  - D1: a recipe no longer measured keeps the colour it had when picked, marked `missing`; the file is still written at its settings
    (they are known and exactly what was picked) and the work asks to pick again or go back to the scale. The plan said the file waits.
  - D4: no separate endpoint. The map asks `GET /api/colors?dots={id}`: the map of the work's laser and lens plus `dots` (what each
    shown colour gives the dots, or why not). Two parallel requests both gathered the map: 0.82 s; one request: 0.63 s.
  - D5: the buttons are «Цвет с карты», «Другой цвет», «На шкалу» (short enough for one row at 1372 px).
- Also: every tonal point of the map carries `image_mode` (its layer's image mode), so a tone of a dot engraving is told without
  reading its pair again. The tones' scales are read once per request (`scale_modes`), not once per tone (0.8 s -> 0.21 s).
  The dots of a dotted work's look are kept in memory beside its stored preview (`photo_work._looks`, 8 looks), so an open work is not
  dithered again on each view (0.49 s -> 0.02 s).
- Walk on the copy (8791, work 37):
  - pick a violet fill: the look, «Точки вблизи», 1503 dpi, 1 h 42 min, file `maxPower=minPower=13.9`, 100 mm/s, 60 kHz, 300 ns,
    0.0169 mm, `ditherMode=atkinson`;
  - undo, width 120 then undo, «На шкалу» 0.18 s, a tone of another scale, refusal of a 0.003 mm fill;
  - no cut text and no sideways scroll at 1771 and 1372 px on the work and the picking map.
- Latency found on the way, none of it made by 0.25.0; to be proposed to the operator:
  - [ ] L1. The colour map opens in 0.57 s: its film model (`/api/oxide/model`, 0.25 s) is requested only after its colours (0.3 s).
        Picking adds 0.06 s (0.63 s).
  - [ ] L2. Any change of a dotted work's look saves in about 0.94 s: the error diffusion of the new look at preview size.
  - [ ] L3. Opening a photo work after any write waits 1.4 s for `/api/grey-scales`, read anew after each write (then 0.06 s).
  - [ ] L4. The first colour map after the app starts takes 4.4 s (0.3 s after): the map is gathered from every pair once. The same on
        0.24.1 with the same data (4.43 s, measured from a worktree of 75b3260 on the copy).
  - [ ] L5. The first picking map after the app starts takes 1.5 s after that (then 0.35 s): the grey scales and the palette of the
        laser and lens are read once. Made by 0.25.0.
- The full suite at first had 3 failures (`test_i18n_coverage`): the new server messages had no Russian. Translated in `i18n-data.js`;
  the reasons a colour cannot be the dots' colour are now the server's (`dot_colours.REASONS`, plain texts), shown through `I18N.tr`
  on the map instead of a second table in `dot-pick.js`. Then 1837 passed, none skipped (`-n 12`, 3 min 15 s).
- Deployed 2026-10-23: commit c1efc10 pushed to main; backup `titanium-before-0.25.0-20261023T152343Z.sqlite` (integrity ok);
  `/api/version` 0.25.0. On 8765 (reads only): `/api/colors?dots=37` 200 (5.7 s cold, then 0.35 s), work 37 shows «Цвет с карты»
  (0.02 s warm). The tabs App and T1 had nothing unsaved and were reloaded.

## 0.25.1 (bug, operator 2026-10-23 «опять несовпадение», «Почему вообще за пределы линейки что-то выходит?»)
Pair 115 (work 39 «Inna Portait Mix 1», IMG_3403, `Inna_Portait_Mix_1_7.lbrn2`): the outlines of layers C11 and C18 lie below the plate,
on the ruler, and the measured window is 132 mm wide on a 100 mm plate. 21 layers match the photograph to 0.1 mm.
- Cause 1: the work exported 60 x 60 mm with C11 (P30 F330 V1300 I0.003) and C18 (P30 F330 V1200 I0.003) hidden in LightBurn: the export
  writes every LightBurn tag of the file a recipe was measured on (`plans._recipe_setting`, DEC-051), the "Show" switch (`hide`) included.
  12 recipes (58 observations) carry `hide=1`. In LightBurn the operator enlarged the work to 100 mm and put it on the plate (35 mm from
  the field's corner); its tools skip hidden layers, so C11 and C18 stayed 60 mm wide at the old place and were engraved off the plate.
- Cause 2: the check knows this case (REQ-050, `left_behind`) and missed it. LightBurn 2.2 saved the file with MirrorY off and reflected
  every shape about the design, hidden ones too; the check turns the engraved file back about its moved cleaning rectangle before it
  compares, which puts a hidden layer 110 mm away from both the export's place and the moved one. So C11 and C18 were measured on the
  ruler and the table (L* 71) and the pair is «Ready to accept».
- [ ] F1. Export: whether a layer is shown (`hide`) and engraved (`doOutput`) is the job's, never the recipe's. NOT DONE, waits for the
      operator: `hide` is part of a recipe's key (`model.parameters_key` hashes every preserved tag), and all 14 recipe settings measured
      on hidden layers have twins measured on shown ones. Exporting the layer shown alone would make a photograph of it measure the twin,
      not the chosen recipe; leaving Show out of a recipe merges the twins and changes their palette ids (DEC-088), so works that chose
      them (work 39: C11, C18) must be moved to the merged entry. Proposed to the operator as a decision.
- [x] F2. Check: compare the engraved file as LightBurn saved it (before it is turned to the plan's axes) with each export turned as
      LightBurn turns a file saved with other mirror switches (`ingest._moved_layers`, before `_normalize_project_to_plan`).
- [x] F3. Tests: a file re-saved with MirrorY changed, resized and moved with two hidden layers left behind leaves them out (the old order
      finds none in the same case); pair 115's own files give C11 and C18 left behind (checked on a copy, not a repository test: the
      operator's files).
- [x] F4. Bug record through markview (BUG-004), README, SemVer 0.25.1; the full suite (1838 passed, none skipped); deployed 2026-10-23
      (commit e75a5c9, backup titanium-before-0.25.1-20261023T192925Z.sqlite, /api/version 0.25.1; tabs App and T1 reloaded). Pair 115 is rechecked only with the operator's
      consent (a write on 8765); work 39 has to be exported again so that its file has no hidden layer.
The colour of photo zones from the colour map (D6) moves to 0.25.2.

## 0.25.2: a layer's Show and Output switches are not part of a recipe (operator's choice 2026-10-23, «Не часть рецепта»)
Why: the export writes every LightBurn tag of the file a recipe was measured on, Show (`hide`) included, so a work's layer came out hidden
(BUG-004); and the key counts the switch, so the same settings measured on a hidden and on a shown layer are two recipes. On the operator's
data: 58 observations (14 settings) carry `hide=1`; their knowledge rows (11) are all `measured`, none questioned or approved, 10 have a
twin row with the same full key once the switch is left out (rows 6 to 14 are the same observations' rows from before the parser kept
`hide`, without evidence since). In the palette one hidden variant pools with its shown twin (602 entries become 601): 12 entry ids change
one to one, and only works 22 and 39 hold them (assignment, variants, undo, layers, layer keys
`e<id>`, exports and what they promised). No finding, proposal or other table names them.
- [x] S1. `lightburn.LAYER_SWITCH_TAGS = ("hide", "doOutput")`: `recipe_settings` drops them (new observations do not store them),
      `model.parameters_key` leaves them out (stored observations key as their shown twins), `plans.JOB_TAGS` never writes them.
- [x] S2. `tools/forget_layer_switches.py`: the palette ids of every laser, lens and titanium keyed with the switches (as 0.25.1) and
      without; each old id that changed maps to one new id (refused otherwise); every plan's stored ids (exact or `e<id>`) are replaced,
      refused if an old id would remain in another form; dry run by default, `--apply` makes a backup copy and an audit entry.
- [x] S3. Tests: the key and the stored settings leave the switches out; an export of a recipe measured on a hidden layer is shown and
      engraved and reads back with its entry's key; the tool's moves, renames, refusal and dry run.
- [x] S4. On a copy: the tool's dry run and apply, works 22 and 39 with no colour missing and the same colours, work 39's export with C11
      and C18 shown; DEC through markview, README, SemVer 0.25.2, full suite; deploy: stop 8765, install, run the tool with `--apply`, start.
      Done on the copy: the dry run names work 22 (6 ids) and 39 (8 ids); without the tool the new code shows 7 and 8 regions «no longer
      measured» and blocks both exports; after it both works show the same colours, regions, layers, time and layer count as under 0.25.1
      (compared with the ids renamed), and their exports have 0 hidden layers (2 before). A second run finds nothing. Knowledge: rows 6-14
      have their evidence again, the hidden rows (31-39, 357, 358) have none, row 611 was created for 358's evidence. DEC-119 recorded.
      Full suite: 1843 passed (`tests/test_tasks.py` now states the key invariant as: every stored observation keeps its key, except the
      2 of the fixture measured on hidden layers, which take their shown twin's key; the old algorithm still reproduces every stored key).
      Deployed 2026-10-23: backup `~/.titanium-platform/backups/titanium-before-0.25.2-20261023T200539Z.sqlite` (integrity ok), 8765
      stopped, the tool's dry run named the same ids as on the copy (work 22 had been edited since: more occurrences), `--apply` (its own
      backup `titanium-before-forget-layer-switches-20261023T200607Z.sqlite`), a second dry run found nothing, 8765 started on 0.25.2.
      Works 22 and 39: nothing missing, export not blocked; exported from a fresh copy of the data: 28 and 23 layers, none hidden or off,
      no hide or doOutput tag. T1 and App reloaded (nothing unsaved). BUG-004's status cannot be set through markview (no bug status tool).
      The operator: export work 39 again.
- [ ] L6. Work 39's view takes 0.61-0.64 s on the copy (5.3 s first after a start, L4) and 0.87-1.98 s on 8765 under 0.25.1: over 0.5 s
      before this change too; to measure where it goes and fix with the operator's approval, with L1-L5.
The colour of photo zones from the colour map (D6) is 0.25.3.

## 0.25.3: the photograph is aligned to the file as it was engraved, scaled or moved (BUG-006, approved 2026-10-23 «Так и сделай»)
Pair 116 (work 22): the operator scaled the whole export, markers included, to the 153 x 153 mm plate (89% x 85% of the 172 x 180.5 mm
export) and engraved that file. The ruler on the photograph (20.2 px/mm) puts the markers 143 mm apart, as the file has them (145 mm), not
164 mm as the plan. The check mapped the photograph's markers to the plan's positions, stretched the photo space by 1/0.89 x 1/0.85 and drew
the file's shapes without the stretch: 120 of 158 vectors «found» by coincidence, 38 «uncertain», wrong colours, no warning.
Design: the engraved file's cleaning rectangle is the plan's extent as the file has it (the invariant `normalize_saved_orientation` already
uses). Its size against the extent gives the scale per axis, its position the offset. The plan's marker geometry (extent, ArUco, QR,
labels) is scaled about the extent's corner to the file's size before the alignment, so the markers found in the photograph are mapped to
where the FILE has them, and the file's shapes are measured as they are, in physical millimetres. The hidden layers that stayed behind
(C12, C15) remain left out (REQ-050). A plate still demands the same size (a scaled plate is a real mismatch).
- [x] S1. `ingest._plan_as_engraved(plan, plate, work_layers)`: for a marked plan that is not a plate, with one cleaning rectangle in the
      file: the scaled copy of the plan's markers (`size` and a new `height` for ArUco, rects per axis) and the placement
      `{"scale": [sx, sy], "offset_mm": [dx, dy]}`; unchanged otherwise. `_align` takes the file offset from the cleaning rectangle for
      every marked plan (today only for a plate); `photo.homography_from_markers` and `registration` honour `height`.
- [x] S2. The report: `alignment.file_placement`; a warning when the scale is not 1 («the file is W% by H% of the export: the photograph
      is aligned to the file's own markers and the engraving is measured at that size»), translated in `i18n-rest.js`.
- [x] S3. Tests: a synthetic vector work whose engraved file is the export scaled 0.89 x 0.85 and moved (markers and cleaning
      rectangle included), photographed at that size: the markers align, every closed vector is found, the colours are sampled on the
      shapes, the placement and the warning are reported; a file at the export's size is unchanged; a plate of another size still refuses.
      These tests must fail on 0.25.2.
- [x] S4. Verified on the copy (port 8791): pair 116 rechecked, 158 of 158 vectors found (mean edge support 0.70 against 0.43), contours on
      the engraving, placement scale [0.8895, 0.8476] offset [19.5, 19.5], the warning in the report. The three new tests fail on 0.25.2
      (the moved-only file too: a work moved on the bed was measured beside its engraving before). Full suite: 1847 passed.
- [x] S5. README, version 0.25.3, full suite 1847 passed, commits 64575b0 (release), a7531b4 (DEC-120), bdbda64 (untracked the foreign
      electron folder a7531b4 swept in). Deployed 2026-10-23: backup `~/.titanium-platform/backups/titanium-before-0.25.3-20261023T231647Z.sqlite`
      (integrity ok), wheel installed, imports ok, 8765 restarted on 0.25.3. Pair 116 rechecked on 8765: 158 of 158 vectors, placement
      scale [0.8895, 0.8476], both warnings, status «Ready to accept»; the T2 tab reloaded. The copy on 8791 stopped.
The colour of photo zones from the colour map (D6) moves to 0.25.4.

## 0.26.0: inscriptions in works (feature inscriptions-in-works, REQ-001..REQ-005, DEC-001..DEC-003; goal 2026-10-23)
Operator: text in a rich set of fonts seen as it writes, stretched, rotated, bent, on a circle or any path, in a chosen colour, cut into
the picture (photo engraving: the place is cut out; vector work: the vectors are trimmed). Answers 2026-10-23: fonts Mac + own + Google;
fontTools, uharfbuzz, shapely approved; English, Russian, Hebrew and others; letters cut with a gap, a backing optional.
Design: an inscription is an object of the work (vector: `colouring["texts"]`, photo work: state key `texts`); letters, cut and backing
are computed from it (memoised) and applied where the work is drawn, timed and written (DEC-003).
- [x] I1. `fonts.py`: catalogue of the Mac's fonts, own files (data/fonts/own) and Google Fonts (metadata listed, a family downloaded to
      data/fonts/google when shown or chosen, bulk download in the background); faces with scripts, kind, named instances; cache by file
      stamps; routes (list, preview SVG, own upload, Google download and status).
- [x] I2. `lettering.py`: the spec checked; runs by direction shaped with HarfBuzz; glyph outlines (variable axes applied) flattened in mm;
      lines, alignment, spacing, stretch, rotation; arc, circle and path (smooth through points), letters upright or bent; polygons union
      (shapely); cut (gap) and backing (rect, oval, outline; colour or clean titanium); clipped to the work; SVG paths; memo.
- [x] I3. Vector work: ops text_add / text_set / text_delete in the colour editor (undo, variants keep texts); layers, areas, row lengths
      and time with the letters; regions trimmed by the cut in the file; photo zones transparent under it; blockers; view with the
      texts' paths. Tests: file read back (no overlap, areas), undo, layers, blockers.
- [x] I4. Photo work: state `texts` (undo, cache keys), ops route; the look, preview and thumbnail with the cut and the letters; the
      file (picture transparent under the cut, text layers after C01, y as the picture); time. Tests incl. read back.
  Done in I4 beyond the plan: the picture is transparent on every pixel the cut touches (`lettering.hole`; the vector work's photo zones
  too), so nothing of it falls into the gap; the objects and parts are found on the whole picture (`photo_state.item(whole=)`); a width
  change scales the inscriptions with the picture, the gap kept in mm (DEC-004); the inscription layers are timed with their scan pieces
  (`engraving_time.loop_pieces`) so the time shown is the file's; a missing or unreadable font is `fonts.FontError`; Google Fonts is in
  the network allowlist of `test_local_operation` (fetched only when the operator asks) and fonts work offline (new test).
- [x] I5. UI `lettering.js`: the «Надписи» tab (list, fields, layout, colour via VectorColours, gap, backing), the font window (search,
      filters, previews, own fonts, Google), the overlay on the picture (select, drag, turn, size, draw and edit a path); in the vector
      editor and the photo work (a stage of the look in mm). Node UI tests; translations of new server messages.
  Walk on a copy of the data (port 8791, tab «ТЕСТ: копия данных, порт 8791 (не настоящее приложение)»; work 40 vector, work 37 photo):
  add, type (Cyrillic + Hebrew), font window (350 Mac families; Google list 2294 families in 2 s; Lobster downloaded on sight; Hebrew
  filter), colours, circle + oval backing, path of 5 clicks, drag (14.1 x 21.2 mm for the pointer's travel), turn about the anchor
  (30.0 deg for a 30 deg gesture), size (radius and height x1.15), undo/redo, LightBurn files of both works (photo: cleaning, picture,
  C02 with the 7 letters), console clean. Found and fixed during the walk (each with a test first):
  - lines below the first on a curve kept the first line's spacing (crowded or squeezed in the middle of a circle): every line now runs
    on its own parallel curve (`along`: 1 - b·k on arcs and circles, the turn of the path on a path), the backing holds every line, and
    `overflow` says when a line is longer than its own circle or letters reach past the centre (arcs too);
  - 9 Mac faces (Corsiva Hebrew, New Peninim MT, Raanana, Mishafi Gold) state sCapHeight -1: the scale went negative and HarfBuzz
    swallowed 378 «math domain error»s in the pen; a cap not stated is now unknown and measured on the letters (catalogue version 2);
  - a family opened on its first face (Thin, Light, Condensed Light): the catalogue now names its regular face (`fonts._regular`);
  - missing Hebrew letters were named in visual order (reversed); the font window opens on the script of the text, previews all its
    lines, and the filters sit on one row; the duplicate «нет букв» warning is gone.
  Seen, not changed (not this feature): a window opened on one screen stays open when the address is changed by hand or by a script.
- [x] I6. README (dependencies, deploy import check), SemVer 0.26.0, full suite (-n 12), deploy after a backup, walk on a copy of the real
      works 22/40 and 35 in a browser (console read), report what is and is not built.
      Full suite 1894 passed (-n 12, 3 min 30 s), none skipped. Commits 2eb7e0b (spec, DEC-005 added from the walk) and 095ba9f
      (release), pushed. Deployed 2026-10-24: backup `~/.titanium-platform/backups/titanium-before-0.26.0-20261024T022814Z.sqlite`
      (integrity ok), wheel installed with fonttools 4.67.0, uharfbuzz 0.57.0, shapely 2.2.0, every import ok, 8765 restarted on
      0.26.0 (350 Mac families; Google not listed until the operator asks). Works 40, 22, 37, 35 read on 8765 (200, no traceback);
      tabs T1 and T2 reloaded, «Надписи» there, console clean. No inscription was added to the live data. The copy on 8791 stopped.
  Not built: a path drawn freehand or taken from the picture's contours (points only); no warning where letters crowd in a tight bend
  of a path; letters go to LightBurn as outlines, not as editable text. DEC-004 and DEC-005 await the operator.

## 0.27.0: the dots of a photo zone take a colour of the colour map; brightness, contrast and gamma of the picture (operator, 2026-10-24)
The operator, on «Яня портрет - 1» (work 41), photo zone 2 in Jarvis: «я не могу выбрать цвет … не могу сделать темнее, светлее».
Found (read only on 8765): the zone's dots sit on its scale 128 mm/s · 60 kHz · 300 ns, measured 6.1..14.3 %, where every power is
nearly black (L* 4..7): the strip under «Точки, %» offers only blacks, and the zone has no «Цвет с карты» (D6 of 0.25, postponed four
times). Nothing anywhere makes a picture lighter or darker before LightBurn turns it into dots.
Answers 2026-10-24: brightness, contrast and gamma (LightBurn's three names); for the dot kinds and for grayscale when «Подобрать серые
под цвета» is off (the picture's own greys); the dots' colour of a zone picked on the colour map as a photo work's (button on the zone
screen and on the zone's card in «Фото»).
Design: the tone is part of the state (`tone`: brightness -100..100 %, contrast -100..100 %, gamma 0.2..5; default 0, 0, 1) and is
applied to the picture's greys (`prediction.adjust_grey`, the formulas already used for LightBurn files) before anything is drawn,
dithered or written: the look, the close-up, the tiles and the file's picture show the same greys; LightBurn's own adjustments stay at
their defaults, so nothing is applied twice. Grayscale with colours chosen by the picture keeps the tone and does not use it.
- [x] T1. `photo_state`: `tone` (DEFAULTS, SETTINGS, checked in `change` by `tone_in`), `tone_used(state)`, `toned(upload, state)` (picture
      and grey_full adjusted, memoised by the upload and the tone; a toned upload keeps `untoned`, so nothing is toned twice).
- [x] T2. Photo work: tone kept and undone (DATA, STATE; an older undo step reads the default); the picture toned where it is cut
      (`_cut_upload` callers), keys of every picture with the tone, the file's picture toned; layer text.
- [x] T3. Photo zone: tone in its settings (copied to a new zone, undone with the editor); look, preview, close-up, tiles and file
      layer toned; key with the tone.
- [x] T4. Photo zone dots from the colour map (D6): `dot_colour` in `photo_zones.changed` (`dot_colours.picked`: a tone of a scale
      moves the zone to that scale and power, a fill keeps `dot_recipe`); a power or a scale returns the dots to the scale; a new width
      takes the recipe's colour there (`at_width`); the file layer, its DPI, the time, the dots, the measured tones and the key at the
      recipe's settings. API `/api/colors?dots=<work>&zone=<n>`.
- [x] T5. UI: «Яркость», «Контраст», «Гамма» and «Как есть» in the shared picture panel (photo work and zone screen), off with a note in
      grayscale with colours by the picture, hidden while nothing can be predicted; the zone screen's «Цвет с карты» / «Другой цвет» / «На шкалу»; the colour map's picking
      strip and «Точки этим цветом» for a zone (back to where it was opened: the zone screen or the editor); the zone's card in «Фото»:
      the dots' colour and «Цвет с карты».
- [x] T6. Tests first for each (state, file read back, undo, API, node UI of both screens and the card), translations of new server texts.
- [x] T7. Walk on a copy (8791) of work 41 zone 2 and photo work 37: pick a colour on the map, move the sliders, compare the preview
      with the file read back, timings warm, console; README, MarkView REQ/DEC, 0.27.0, full suite (-n 12), deploy after a backup, report.

Review (2026-10-24). Walked on a copy of the data (database and files, every stored path rewritten into the copy, port 8791, tab «ТЕСТ:
копия данных, порт 8791 (не настоящее приложение)»), then the copy stopped:
- Work 41 zone 2: «Цвет с карты» opened the map for the zone (170 fills and 314 scale tones of laser 1 / lens 2 can be the dots); a blue
  fill (60 % · 250 mm/s · 300 kHz · 2 ns, step 0.01 mm) came back to the zone screen with «Другой цвет» / «На шкалу», the time 56 min;
  from the editor's card a scale tone moved the zone to 150 mm/s · 250 ns at 14.38 % and came back to the editor's «Фото». The file read
  back: Image layer, Jarvis, Min = Max = the fill's power, its speed, frequency, pulse, step, DPI 25.4/step; LightBurn's Bitmap settings 0/0/1.
- Tone on the zone: brightness +20 → struck dots 44.9 % → 24.8 %, gamma 0.7 → 34.6 %; the file's greys = adjust_grey(plain) ±1. One
  request per slider drag (1.5 s on the 150 mm zone, the same as an old dot-power change); the map in picking mode 0.52 s warm.
- Work 37 (grayscale, greys by colour): sliders off with the note, the file unchanged; with own greys the file = toned ±0; Jarvis
  brightness +20 → 37 % struck against 56 %; six undos back to as it was. Console and server log clean.
- Found on the way: the sliders were 30 px wide (label, slider and number in a 190 px cell) → each name with its number above a full-width
  slider; the tone was shown while the scale is not measured → hidden, like the power sliders.
- Memory: the app process grows to about 2 GB after work on the 150 mm zone; main (0.26.0) does the same (1.9 GB for the same steps), the
  tone memo adds about 0.1 GB. Not changed; reported to the operator.
- Full suite: 1909 passed, none skipped (-n 12, 3 min).
- Deployed 2026-10-24 06:25 UTC: backup `~/.titanium-platform/backups/titanium-before-0.27.0-20261024T062524Z.sqlite` (integrity ok), the
  0.27.0 wheel in `~/.titanium-platform-app` (imports checked), the app restarted on 8765; work 41 zone 2 read as before (Jarvis 12.8 %,
  tone as it is, no recipe). Tabs T1 and T2 reloaded (v0.27.0, «Яркость», «Цвет с карты» on T2), consoles clean. Nothing was changed in
  the live data.

## 0.28.0: everything left in MarkView that can be built, Electron excluded (operator, 2026-10-24; plan approved)
Operator: «Пройдись по всем MarkView Issues, Features и Bugs, выбери те, которые ты можешь сделать, и сделай их все, кроме ... Electron».
Survey: BUG-001..006 are fixed in code (0.5.2, 0.18.2, 0.21.1, 0.25.1-0.25.3); MarkView keeps their status itself. Built here:
- [x] V1. REQ-047 crit. 8: an old file's promise is reconstructed only while the work's colouring and split are the file's; after a recolouring the review claims nothing.
- [x] V2. Vector work: «Разбить заново» warns before it resets the colouring (I-8); «Цвет выделенному…» in the editor's selection (I-5 gap).
- [x] V3. Same-recipe neighbours joined into one shape in the LightBurn file and the time (I-7), the stored split untouched.
- [x] V4. Recolouring modes «Контраст соседей» and «Художественно» with a palette subset (I-6, DEC-079).
- [x] V5. Region density as a slider with the region count before the rebuild (I-2).
- [x] V6. Eyes: detail per area, moved/resized boundaries, a manual area's kind; the colours outside a changed area stay (I-3).
- [x] A1. Inscriptions: Enter / double click end a path (REQ-003), freehand path, warning where letters crowd on a tight bend of a path.
- [x] B1. «Приложение обновлено» banner; AI client failures as messages in the research chat and the explainer; overscan and line interval
      shown (REQ-054 crit. 3); dot width correction of a dot kind written to the file (K2).
- [x] A2. Inscriptions: a new one takes the last font used (after a reload from the work's undo); its colours in the editor's colour window, vector and photo work.
- [x] T. Tests for criteria that were built but unproven: inscriptions REQ-001..REQ-005, photo-zone-dots REQ-001/REQ-002, REQ-047 c1-c7.
- [x] A3. Font window: a bulk download of a kind with no script, a family chosen before it is downloaded is downloaded and chosen
      (REQ-001 c2, found by the tests of T).
- [x] R. MarkView decisions and ticked criteria, issue #32, README, 0.28.0, full suite -n 12, walk on a copy (8791), deploy after a backup, report.
Not taken (operator or real data needed): Electron; Q-026..Q-029; acceptance of proposed DECs; DEC-088 automatic re-measure; REQ-053 crit. 5/6;
REQ-052 crit. 4 (LightBurn on the real file); a text path from the picture's contours; editable LightBurn text.

Review of 0.28.0 (2026-10-24):
- Built: V1-V6, A1-A3, B1 above, each with its tests; vector-detail's eight criteria and every inscriptions criterion ticked; the three
  features worked on (vector-detail, inscriptions, the platform) set to implemented. DEC-090..DEC-094 of vector-detail are proposed.
- Walk on a copy of the data (database and files, 207 stored paths rewritten, none left pointing at the live folder; port 8791, stopped):
  work 22 density 60 / 100 / 200 -> 150 / 301 / 719 regions, the count in about 1.9 s, again from memory in 0.4 s; work 40: the rebuild
  warning, one eye at «максимально» with a moved boundary, the preview's 367 regions = the split's 367, centres kept, 99.997 % of the
  pixels outside the eye unchanged, 45 -> 64 regions inside it; Contrast and Artistic (warm, twice: two variants); a region painted like
  its neighbour: 339 -> 338 shapes in the file, undo 339; an inscription's colour window (626 colours), a freehand path ended by Enter
  (5 points); dotWidth 0.05 / useDotCorrection 1 in photo work 37's file, none when off; the update banner. Console and server log clean.
- Timings not met: the vector screen of work 22 takes 0.67-0.74 s (as in 0.27.0, REQ-047 crit. 9 open); a recolouring of work 40 takes
  1.6-2.8 s; a rebuild 5-6 s.
- Not taken: Electron; Q-026..Q-029 and photo-zone-dots Q-001; acceptance of proposed DECs; DEC-088 automatic re-measure;
  REQ-053 crit. 5/6; REQ-052 crit. 4; a text path from the picture's contours; editable LightBurn text.
- Released: full suite 2015 passed (none skipped), main pushed, tag v0.28.0, issue #32 commented and closed (no open issues left).
  Deployed: backup titanium-before-0.28.0-20261024T122028Z.sqlite (integrity ok), wheel into ~/.titanium-platform-app, 8765 restarted,
  /api/version 0.28.0; read only: vector 22/39/40/41 and photo 35/37 open (work 22 warm 0.67-0.89 s), export of 22 2.7 s (photo zones'
  pictures 1.95 s as before, the join 0.22 s), app.log clean. Open pages need a reload (Cmd+R) to get the 0.28.0 screens.
