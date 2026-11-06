# UX P0 validation results (releases 0.39.0 and 0.39.1)

Record of what was run for feature `ux-validation-p0` (REQ-001..003). Protocol: [ux-p0-protocol.md](ux-p0-protocol.md). Data guarantees,
legacy documents and the list of changed tests: [ux-p0-guarantees.md](ux-p0-guarantees.md). Date of every check: 2026-11-05.

Build under check: commit `c89b339` (0.38.1) plus the work of the nine `ux-*-p0` features, released as 0.39.0 (commit `4b8a783`); the
finishing pass of the forms (section 2c) is 0.39.1.
Nothing in this record is a claim of measured improvement: no before/after timing was taken (section 3).

States: `passed` (where), `failed`, `not executed` (why). A check that was only read in code has no state.

## 1. Full automated suite

| run | command | result |
|---|---|---|
| all tests, tree finished | `.venv/bin/python -m pytest -q -rs -n 12` | 2924 passed, 0 failed, 0 skipped (454 s) |
| final run, version 0.39.0, all docs and statuses in place | same | 2925 passed, 0 failed, 0 skipped (357 s) |
| release gate of 0.39.1 (forms finished, control sweep test added), version 0.39.1 | same | 2931 passed, 0 failed, 0 skipped (443 s) |

Node tests run screens on the fake DOM of `tests/ui_dom.js`. It now keeps real focus bookkeeping (`activeElement`, `contains`, removal of a
node loses focus) and throws on assignment to names a built-in DOM element owns (`label.control` in Chrome is a read-only getter: an
assignment passed in node and would have broken every form in a browser). It still keeps no layout, no real key handling, no screen reader.

## 2. Seen in a real browser

Two kinds of evidence, kept apart.

**(a) Lead, MarkView browser tab (Chrome), `http://127.0.0.1:8801`, a throw-away workshop built by `tools/seed_ux_workloads.py --count 200`
(200 stock records, 200 works; never the live workshop, never port 8765).** Window about 1190 × 900 CSS px, text 100 %.

| id | scenario | observed | state |
|---|---|---|---|
| R1 | multi-character search in the works catalog | typed «Work 16»: value kept, same input node connected, focus kept, caret at 7, 15 rows | passed |
| R1 | search with no match, then reset | text «Работ по этим условиям нет», the condition named, «Сбросить поиск и фильтры» restores 20 rows and an empty search | passed |
| R2 | two clicks on «Показать ещё» in one tick | one request (`offset=20&limit=20`), 40 rows, no duplicate row | passed |
| R3 | stale answer: «Work 1» held 2.5 s, «Work 19» typed meanwhile | the list stayed that of «Work 19» (15 of 15) before and after the slow answer arrived; it never became «Work 1» (111 works) | passed |
| R4 | save failure: material form, the first `PUT /api/materials/200` answered 500 (injected once, then passed through) | the error stays beside the form («Не получилось отправить… Всё, что вы ввели, осталось в форме»), the typed name kept, same input node; a second press saved (server name changed), the error left, «Материал сохранён» shown | passed |
| R5 | back navigation: search «Work 16» + gallery view, open a work, `history.back()` | search «Work 16», gallery pressed, «15 из 15» restored; the address carries the place (`at=vector-168`) | passed |
| R6 | dialog: Tab from the last control | focus wraps inside the dialog; the page behind is inert | passed |
| R6 | nested dialog (material selector over the context dialog) | Escape closes only the top one; focus returns to the opener button inside the remaining dialog; second Escape returns it to «Изменить…» | passed |
| R7 | skip link on `#/works` | route unchanged (`#/works`), focus on `#main` (`tabindex=-1`) | passed |
| — | catalog with 200 works | 20 rows, «показано 20 из 200», chips by kind with counts, filters laser / lens / stock, «Показать ещё 20» | passed |
| — | material list in settings, 200 records | 20 rows, search, sort, filter, one «Изменить» per row, no form open | passed |
| — | change-context dialog | one selector line for titanium (no option per record); the nested dialog lists 20 of 200 with search and grade filter | passed |
| — | creation wizard step 1 (`#/new`) | heading focused after render, three steps shown, the shared context card with «Изменить…», no horizontal overflow | passed |
| — | task panel | «Задачи» opens the panel, `aria-expanded=true`, focus on «×»; empty state text shown | passed |
| — | sweep of 20 routes | no console message at all; no horizontal overflow | passed |

What the sweep also showed, so that nobody reads it as a defect of the redesign: on the synthetic workshop `/vector` and `/photo-engraving`
show «Не удалось загрузить данные» with «Повторить» because the seeded works are catalogue rows without their documents (`document_path`,
`image_name`). The failure state itself (message, retry, nothing half drawn) is the R4 first-read-failure path. `#/knowledge` without an id
fails as it did in 0.38.1 (the route is `/knowledge/<id>`).

**(b) Agents, headless Chrome driven over the DevTools protocol, own profile, throw-away servers on ports 8797 and 8799.** Viewports were
**emulated** (device-metrics override); «200 % text» was emulated by multiplying computed font sizes once per load, not by the browser's zoom.

| area | observed |
|---|---|
| layout, 26 routes at 320 × 640, 800 × 600, 800 × 600 with 200 % text, and 1280 | no horizontal overflow, no real clipping (remaining clip hits are visually hidden helper text) |
| keyboard walk menu → catalog → dialog → editor panel → colour → export → «← Мои работы» at 320 and at 800 × 600 | visible focus ring at every stop; dialogs return focus to their opener; after «Скачать LightBurn» focus stays on the new button |
| editor panel at ≤ 1100 px / ≤ 480 px | slides in / bottom sheet of at most 60 % height; hidden when closed, out of the tab order; Escape and «Закрыть панель» return focus |
| lifecycle strip at 320 px | folded; height 415 → 102 px |
| photo engraving save failure at 320 | error beside the work, page fits (failure forced by a faked 500) |
| task panel at 320 and at 800 × 600 with 200 % text | Escape and «×» return focus to the header button |
| all 100 scripts load; `App.field`, `Forms`, `SaveState`, `Operations` work against a real DOM; nine screens visited | no script error |
| ingest review of one seeded pair, three sizes | layout only |

**(c) Control sweep of 0.39.1 (agent, headless Chrome over the DevTools protocol, own profile, throw-away workshop on port 8813, built through
the real API with real vector, photo and ingest documents).** Every `input`, `select`, `textarea` is checked for an accessible name
(`aria-label`, `aria-labelledby`, `label[for]`, wrapping label) and every numeric box for a unit and a range in its name or description.

| scope | controls scanned | without a name | numeric | numeric without unit | numeric without range |
|---|---|---|---|---|---|
| real browser: `/vector?new=1&classic=1`, an open vector work (colour, area, photo-zone, file tabs), `/photo-engraving?work=…`, `/photo-preview`, `/ingest` with a pair review, `/devices` with the lens tab, `/network`, `/labs`, every `/setup` tab, `/designer`, `/plan/…`, `/experiment/…`, `/findings`, `/colors`, `/research`, the plate dialog of every plate type | 783 | 0 | 357 | 0 | 0 |
| node (`tests/test_every_control_named_ui.py`: 40 screens and tabs, 18 dialogs, every plate type) | about 671 | 0 | 266 | 0 | 0 |

The first browser sweep found 12 numeric boxes without a unit (the Lab boxes of the target colour); they were fixed and the sweep repeated.
«Range» means the range the server enforces; a quantity with no server rule has a name and a unit and no invented limit. Not reachable in a
throw-away workshop: a state that needs a running laser job and a live cloud sign-in; six list-row steps had no expandable rows.
Server refusals of the plate dialog, the new-work dialog of photo engraving, the shooting-rig editor and chart-reference form and the
controller table now stay beside the form with the typed values; about 33 quantities in `forms.js` are compared with the Python rules by
an edge test. Final run of the interface tests of this pass: 638 passed, 0 failed, 0 skipped.

## 3. Not executed

| id | check | why |
|---|---|---|
| T1–T10 | before / after timings of the ten operator tasks, success without a hint, returns, mistaken actions, lost changes | need the operator at the controls on a rehearsal copy; the baseline sheet below is left unfilled. No numeric target is set (research n57) |
| A2 | screen reader announcements (VoiceOver) of stage changes and final outcomes | needs a person with a screen reader |
| A7 | Electron: keyboard path, 320 px, 800 × 600, 200 % | the packaged app was not driven; the packaged `--smoke` of the release build checks start-up only |
| A1, A3, A4 | the same profiles in a real, resized window and the browser's own zoom | only emulated (section 2b) |
| — | ingest-review overlay move / rotate / scale, detail candidates on a real photograph | no seeded photograph pair was driven by pointer |
| — | focus order and trap with nested dialogs under a screen reader; announcements of tiles, impact panel, radiogroup | needs a screen reader |
| — | a task actually running in the task panel while the person moves to another screen | panel tested in node and opened empty in a browser |
| — | real file picker and drag and drop; quitting and relaunching Electron during a starter test | restart simulated by a second screen run against the same server |

Baseline sheet (fill by the operator; one row per run):

| build | date | operator | task | success without a hint | time to find the record | time to the downloaded file | returns | mistaken actions | context entered again | changes lost | keyboard only |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.38.1 | | | | | | | | | | | |
| 0.39.0 | | | | | | | | | | | |

## 4. Domain guarantees and legacy documents

All nine guarantees hold and none was weakened; old documents (artwork, unreachable colours, stripes, photo-preview, photo work) are
created, reopened and exported as before, including a workshop made by 0.38.1 itself opened by the current code. Evidence, mutation
checks and the list of existing tests changed by the nine features: [ux-p0-guarantees.md](ux-p0-guarantees.md). No old screen was removed.

## 5. Findings of the validation

- F-1 and F-2 of the guarantees record are closed (a stale fixture; the two halves of the palette guard of photo engraving now have a test each).
- The photo-engraving stale-answer guard was the only guarantee whose test did not distinguish its two conditions; it does now.
- The synthetic seed builds catalogue rows only. Loads of 20 / 200 / 2000 therefore exercise the catalog, the materials list, the
  selectors and the knowledge lists; they do not exercise the vector or photo editors.

## 6. Questions left for the operator

1. A rejected photograph result keeps the existing soft delete (pair record stays, uploaded files are purged); a separate «rejected» status
   would change the stored format. Decide whether it is wanted.
2. An accepted pair has no manual tools; a correction is a new pair («Поправить совмещение этого фото»). Say if «during review» should
   also cover accepted pairs.
3. A hand-placed anchor on an existing pair now wins over automatic alignment when the pair is checked again (needed by DEC-001 of photo
   review); before, it was only a last resort.
4. The text strategy and the layer task exist only in the classic vector form (`/vector?new=1&classic=1`); the wizard offers the four
   results. Say whether the wizard should offer them.
5. Server user errors carry no field name, so only validation lists map to fields; a refusal that names no field is shown on the form with
   what to do. A `field` key on the backend would put more messages beside their inputs. Speed has no documented limit, so none is enforced.
6. The list of background tasks is not saved across a restart (the panel says so).
