# Lessons

Rules written after the operator's remarks, to prevent a repeat.

## Screens follow the operator's questions, not the data model
- Remark: experiments were shown as plates, engravings and photographs in three columns; the colour map was reached through profile versions and experiments.
- Rule: before building a screen, write the one question the operator asks of it ("what happened in this experiment", "where did this colour occur") and make that the
  structure. Derive the object from existing data (experiments are derived, nothing new is stored) instead of exposing tables.

## What the operator must see is shown, not offered
- Remark: the photograph with its overlay must be shown in an experiment every time, not hidden behind a button.
- Rule: evidence for a result (photograph, overlay, contours) is the first block of the page and is on by default. Buttons may switch it off, never on.

## Do not ask for what was already given
- Remark: "I gave you the card / the pair, why can you not use it?" (the ColorChecker was part of the LightBurn file; the pair was already supplied).
- Rule: before asking for an input, list what the conversation and the stored data already contain and look inside it. Ask only for what is provably missing.

## A "did not hit" screenshot is a geometry bug until proven otherwise
- Remark: the overlay of the photo engraving missed, and the green lines were missing.
- Rule: check registration on the real photograph in the real application after every change, not only on synthetic data; the overlay must draw every layer of evidence
  (silhouettes, window, hidden parts). Constrain refinements physically (perspective limit) so a good score cannot hide a skew.

## Synthetic tests are not validation
- Rule: every algorithm that reads real photographs is also run on the operator's real pairs before it is called done; record the numbers (anchors, residual mm, rank
  correlation) in tasks/todo.md.

## Do not end a turn by asking what else to fix
- Rule: finish the listed scope, verify it, report; list open items as facts, not as a question to the operator.

## An optional physical feature is never a required input of an algorithm
- Remark: "why does the algorithm use the frame at all? find every section of the file on its own and grow from there" (2026-10-18), after three
  new pairs were refused for "no frame window".
- Rule: the input of a registration is the file geometry and the photograph, nothing else. A frame, a chart, a marker may *help* when present
  and must be *derived* (the frame from the known plate size) when they matter, but a missing one must not stop the work. Before writing a
  detector of X, ask what happens to the operator's pair when X is absent or looks different (glossy, dark work touching it).

## Judge an overlay by numbers, not by eye
- Remark: I told the operator the lion's fallback overlay was "mirrored and shifted"; measured against the anchored result it was off by 0.4 mm
  median and up to 2 mm at the edges, not mirrored.
- Rule: before calling a registration wrong, compute the displacement against a trusted transform on a grid in mm and quote that; a 1000-px
  preview cannot tell 2 mm from a mirror.

## A relative measurement is shown against a reference in the same photograph, never as the camera exposed it
- Remark: "it does not find light colours" (2026-10-18): every colour of a chartless pair was near black because the photographs are
  2.5–5 stops under and the RAW was decoded without any brightness change.
- Rule: a value that depends on exposure or illuminant is evidence, not a colour. Before showing or comparing it, anchor it to a reference
  inside the same photograph (clean titanium from the cleaning layer, a chart when present) and say which reference was used. If no
  reference exists, say so on the screen instead of showing dark numbers as if they were colours.

## A calibration is checked on its own reference before its result is believed
- Remark: "why no black" (2026-10-18). The chart correction had been reporting a mean residual of 6 dE for months; nobody looked at *where*
  the residual sat. The grey ramp showed the dark tones threefold too dark.
- Rule: every calibration step reports its result on its own reference in a form a person can read (the grey ramp beside the reference), and
  a mean residual is never accepted without that breakdown. When a measurement looks physically odd, check the calibration's reference first.

## A fallback never widens what is measured
- Remark: "clean titanium is visible only where there is no fill; every layer must be taken into account" (2026-10-18), after a fully
  engraved-over first layer was reported as clean titanium at L* 50 over the whole plate.
- Rule: when a mask comes out empty, the answer is "nothing visible", stated on the screen; a fallback for thin strokes applies to thin
  strokes only. Coverage by later layers is computed over every layer in burn order before anything is sampled.

## Recognition that reads text is tuned on every real sample at once, never one at a time
- Situation (2026-10-18): reading the engraved labels of six Material Test photographs; every fix that made one photograph read better
  broke another (a global threshold, a geometric crop, a strip read), because the photographs differ six-fold in label contrast.
- Rule: keep one runner over all real samples and judge every change by the whole table; prefer local, self-calibrating measures (a
  threshold per label from its own strokes) over global constants; let structure repair reading (an evenly spaced sequence fixes a
  misread digit) instead of chasing a perfect reader; and leave the last word to the operator's confirmation.

## A new kind of experiment is finished only when its results are on the colour map
- Situation (2026-10-18): the matrix experiment was built and its six photographs uploaded, but every pair stopped at "settings wait
  for confirmation"; the operator had to remind: "do not forget to add the results to the colour map".
- Rule: the end of a data path is where the data is used (the colour map, the model), not the review screen. Take real samples all the
  way: verify each proposed reading against the photograph, correct what is visibly wrong, accept, and check the map counts. What
  cannot be verified (an unreadable value) is named to the operator with exactly what is missing.

## A model's note that asks for data is re-read when that data arrives
- Situation (2026-10-18): the kinetics note said "plates with a monotone dose ramp at one pulse regime are needed". The matrices
  brought exactly those plates, the results went onto the map, and nobody looked at the kinetics again; the operator found it
  still asking for ramps, in English, under a stray "null".
- Rule: when new data feeds a model, run the model and read its output on the screen the operator uses, including notes. A note
  that promises "with X it will work" is a hypothesis to test the moment X exists.

## UI text: what h() forgives, the DOM does not
- `el.replaceChildren(cond ? x : null)` prints "null"; `h()` skips null. Use `App.fill(el, ...)` (static test in test_ui_files).
- Server text reaches the screen not only through raised errors: dict literals ({"note": ...}) and conditional messages count.
  The translation coverage test collects them; a new kind of message site must be added to the collector, not translated ad hoc.

## A constraint that forces order manufactures correlation: check the physics before trusting r2
- Situation (2026-10-18): forcing the film thickness to grow with dose along each matrix gave "usable" kinetics laws
  (r2 0.6-0.85), but the exponents were 2-5.6 and the palest, almost bare cells sat at 96 nm or the path skipped the whole first
  order. Any monotone assignment correlates with dose; the r2 said nothing.
- Rule: before reading a fit statistic on data shaped by a constraint, check the assignment against what is physically known
  (pale cells are thin, the first order comes first). When the approved plan's premise fails on real data, switch the new
  behaviour off, keep it tested, say why with numbers, and bring a revised plan instead of tuning until a number looks good.

## The operator's application never runs from the development tree
- Remark (2026-10-18): "не работает" / "Sttus не поменялся". Port 8765 ran from the repository's editable `.venv`: its Python
  code stayed in memory while the UI files were served from disk, so the new screens called routes the old backend lacked.
- Rule: the operator's server always runs from the installed wheel in `~/.titanium-platform-app` (DEC-024), never from the
  working tree; check `ps` for the 8765 process before changing files. A new version reaches it only through the deploy step,
  after a backup of the database.

## Statuses move with the code, not at the end
- Remark (2026-10-18): the plan's status table and the requirements' acceptance criteria stayed "in progress"/unchecked while
  work landed on the branch.
- Rule: every commit that implements or verifies something updates, in the same push, the plan.md status row, the ticked
  acceptance criteria (code + test seen) and the issue comment/label.

## Test servers never appear in the operator's browser
- Remark (2026-10-18): "не удали мои эксперименты … фотографий нет, выводов нет". A worker had opened its test server
  (port 8791, a database copy without the photo files) in the operator's MarkView window; the operator took it for the real app.
- Rule: workers never use the MarkView browser tools; UI is checked by static tests and API calls. The lead checks a new version
  on a full copy (database and files) before the deploy, and says in every message which port is the operator's (8765).

- Again (2026-10-19): "Ты запустил, собственно говоря, аппликацию локально, как раньше. В чем дело?" A copy of the data served on 8794 was
  opened in the operator's window as "Editor 8794 (copy)" and the operator worked in it, so a re-split and paints went to a copy.
- Rule added: a goal that says "open the running app in a tab" means the operator's app on 8765 (after the deploy, view only: select,
  hover, read; never an operation that changes the work). A copy is only for a flow that changes data; its tab is named "ТЕСТ: копия
  данных, порт N (не настоящее приложение)" from the first moment, and its server is stopped as soon as the check is done.

## A confirmation that adds no information is a defect
- Remark (2026-10-19): "Мне нужно каждый принять, принять. Очень неудобно … все должно быть принято в самом начале." Every colour
  outside a ΔE tolerance of 0.05 waited for its own "accept" click (28 on one work); the nearest colour and its ΔE were already shown.
- Rule: before adding an approval step, name what the operator learns at that step that the screen does not already show. If
  nothing, apply the choice and show the warning (a ΔE badge, an outline) instead. A tolerance chooses between candidates; it does
  not stop the work.

## A local screen that takes seconds is a bug: measure every screen on the real data
- Remark (2026-10-19): "Почему тэбы грузятся долго? Это ведь локальный вызов." Knowledge took 6.8 s (summaries recomputed per
  entry, O(N²)); every photograph was decoded from RAW on every request (0.6-3.3 s, 2 MB PNG per thumbnail).
- Rule: after a release, time every screen's requests on the live data (curl, GET only) and treat anything over 0.5 s as a
  defect. Derived pictures are cached by a key of all their inputs; a list computes shared data once, never per item.

- Again (2026-10-22, 0.22.0, found in my own walk): the tiles of a photo zone each recomputed the zone's scale and dots (a list computing its shared data
  per item), and every new request was over 0.5 s. Rule kept: time each new request warm and after a change, sequentially, before the release report.

## The node DOM of the UI tests is not a browser
- Mistake (2026-10-22, 0.22.0): `querySelectorAll(...).map` passed every node test (`tests/ui_dom.js` returns arrays) and threw in the browser on the
  first load of every vector work. Found only by the walk.
- Rule: in UI code spread a NodeList before array methods (`[...el.querySelectorAll(s)]`); `test_no_ui_script_uses_a_node_list_as_an_array` checks it.
  A new screen is not done until it was opened in a real browser (on a copy) and its console read.

## A framework default is not a contract
- Situation (2026-10-19): CI failed on all three jobs between two runs of the same tests: FastAPI 0.148 began reading a
  missing `bool` form field as false (an unticked HTML checkbox), and the route relied on `Form(True)`.
- Rule: a form flag whose absence must mean "yes" is read as text and parsed by the application (`form_flag`). When CI
  breaks without a code change, compare the installed versions of the last green run with the failing one first.

## Profile before promising what a smaller output saves
- Situation (2026-10-19, BUG-001): the plan expected small list thumbnails to open noticeably faster cold. cProfile on the real RAW:
  the 2 MB PNG took 33 ms to encode, the RAW decode 520 ms (92 % of the request); `size=480` saved 87 % of the bytes and 5 % of the time.
- Rule: before choosing a fix for a slow response, split its time by stage on real data (decode, compute, encode, transfer) and state
  which stage the fix removes. A cost that cannot be removed (an unchanged decode) is paid once and kept (cache, warm-up), not shrunk.

## A decision to close a feature is not a change of its status
- Remark (2026-10-19): "Почему titanium-color-engraving-intelligence-platform в статусе implementing? Закрой фичу". The operator had closed that
  feature the same day; DEC-079 and PR #26 recorded it, yet `overview.md` still said `implementing`.
- Rule: MarkView records the implementation stages (implementing, implemented, verified) itself and `markview_set_status` accepts only
  idea..ready. After writing a decision that closes a feature, run `markview_list_features`, and if the stage did not move, say so to the
  operator and name what moves it (the app); never claim "closed" on the strength of a decision file, and never hand-edit the stage or
  `.dde/state.db` to make the list look right.
- Superseded for the stage line (2026-10-24): «Не забывай обновлять статусы в MarkView, каждый фичинг, которыми ты работаешь.» MarkView reads
  the implementation stages from branches and pull requests, and work goes straight to `main` (project CLAUDE.md), so nothing moves them.
  Rule now: at the start of work on a feature set `status: implementing` on the first status line of its `overview.md` (a script, one line,
  as 11b11fa did), and at its release `implemented` once every criterion it claims is ticked with a test; never `verified` (the operator's
  walk). While working: record each new decision with `markview_add_decision` (proposed) when it is made, tick a criterion when its test
  passes, commit these with the code, and run `markview_list_features` to confirm. Never touch `.dde/state.db`. Decision ids are per feature
  (vector-detail has its own DEC-090): cite them with the feature's name.

## Committing another feature's specification is not building it
- Remark (2026-10-19): "Пока я не вижу, чтобы ты векторную работу перенес на третье место, и не вижу, где можно выбрать алгоритмы по разбивке."
  The specification of vector-detail-and-colour-control (issue #32) had been committed on the editor's branch at the operator's decision, and
  the operator expected its screens to appear too.
- Rule: when a goal names one feature folder, say in the same message that any other folder committed with it is specification only, which of
  its criteria are not built, and which of them wait for an answer (here: the list of splitting methods is still open in its own discussion).
  Never leave "committed" to be read as "done".

## A choice that does not change the picture is not a feature, and a knob must do what its label says
- Remark (2026-10-19, with a screenshot of 0.7.0): "1 - Всё криво, 2 - Алгоритмы не делают разницу, 3 - нет возможности гладких линий,
  4 - нет возможности окрасить при помощи AI". I had reported 0.7.0 as done after checking the DOM and the tests, not the picture.
- What was true: (1) `.toolbar{align-items:flex-end}` with hints under only some fields put four labels at four heights; (2) SLIC and SEEDS
  give the same map (my own table said ΔE 7.35 vs 7.47) and I shipped the pair anyway; (3) "Сглаживание границ, мм" is the Douglas-Peucker
  tolerance, so a larger value makes lines MORE angular, while the real low-pass is a fixed 1.2 px (0.15 mm); (4) the AI idea was only a
  draft with open questions, although the operator had said "доделай всё".
- Rules: before reporting a visual change, look at the real screen and at a zoomed crop of the output, and say what I saw. Before offering a
  choice between methods, put their outputs side by side; ship only options whose outputs visibly differ, and say so when they do not.
  A control is named after the effect it has on the result (check by turning it to both ends). An open question about a feature the operator
  asked for is mine to answer with a recommended default and an approval request in the same message, not a reason to leave it unbuilt.

## Build what the operator asked for most first, not what is easiest to finish
- Remark (2026-10-19, during 0.8.0): "Я нигде не вижу, чтобы AI мне подобрал цвета по каким-то своим принципам. Почему ты это никак не добавишь?"
  and "Что ещё кроме неё осталось? ... почему так долго?". The plan listed layout, smoothing, methods and only then the AI colouring, so
  three commits went out before the one capability the operator had asked for twice ("доделай всё") existed.
- Rule: order the steps of a plan by what the operator named as missing, newest capability first; a polish step never goes ahead of a
  feature the operator asked for. When a request has several parts, say in the first message which part comes first and when the one the
  operator cares about most will be visible. Answer "what is left" with the full list of what remains, without being asked twice.

## Run the tests that touch the change while working; the whole suite once, at the end
- Remark (2026-10-19, voice-typed): the operator asked to stop running every test after each change, run them all once at the end, save
  time and reach production as fast as possible. The full suite takes about 12 minutes; I had been running large parts of it per step.
- Rule: while building, run only the test files of the code just touched; run the whole suite once before the release commit (in the
  background while the release steps that do not depend on it go on), then back up, deploy and look at the real app.


## Install the declared dependencies when deploying a wheel; a missing one must not end as a bare 500
- Remark (2026-10-19, after 0.8.0 went to production): "не могу раскрасить с помощью AI - Ошибка сервера (500)". The deploy recipe
  `pip install --force-reinstall --no-deps <wheel>` never installed `openai` (declared in pyproject.toml) into `~/.titanium-platform-app`, so the
  first real AI call there raised ModuleNotFoundError. My own real call had run in the repository's `.venv`, which has it, so the check
  passed and the deployed environment was never exercised.
- Rule: after installing a wheel into the app environment, import every declared dependency from that environment
  (`~/.titanium-platform-app/bin/python -c "import openai, ..."`), and make the first feature check of a release from that environment, on a
  copy of the data, not from `.venv`. The deploy recipe in README gets a second step that installs the missing dependencies.
- Open: a failure to build the AI client should reach the operator as a message, not as "Ошибка сервера (500)" (needs approval, see todo).

## A restore from a backup brings back the state of the backup, not the state before the deletion: compare and say so
- Mistake (2026-10-19): work 22 was deleted at 21:37:34Z; I restored it from the 21:04Z deploy backup and reported "restored". The work had
  been changed after that backup (21:35:15 a new split "По тонам", then the photo permission, settings and the colouring "Сохранить тональность"
  until 21:36:39), so the restored work was the older one (document version 7, SEEDS, 6 layers) and I did not know it. I only found it after the
  next release when the list screen showed the real numbers, and my report also quoted figures (16 layers) that came from the test copy,
  not from the real data.
- Rule: before calling a restore done, compare the restored row's last change with the time of the deletion (audit), look for newer files of
  the same work in the store (`files/` modification times in UTC; here `vector-075cbfd7c547.json` was newer than the restored document), and
  look in the snapshot taken just before the restore: freed pages keep the deleted row's text (history with times, document path). Tell the
  operator which state came back and what, if anything, is newer and missing.
- Rule: figures in a report about the operator's data come from the operator's data (the real app's API), never from a test copy.

## Two screens that reach one delete must each say what it deletes; and an "unknown actor" is first the operator's own click
- Mistake (2026-10-19): the operator deleted an "experiment" and their vector work was gone. The list of experiments showed every plan, a vector
  work included, and "Удалить эксперимент" deletes the plan; for a work nobody had photographed the plan is the work (picture, split, all
  variants, `plan_deleted`), while the confirmation spoke of "плата и все проверки (0)". The plan page of a vector work had the same button.
  Twice before I had found plans missing from my test copy (22 to 24, then 22 again) and wrote "an unknown actor / a fork": it was the operator
  clicking in the tab I had opened on the copy, through this very path.
- Rule: when one destructive endpoint (here `DELETE /plans/{id}`) is reachable from several screens, list every caller and check that each
  names the object it really deletes; derived objects (an experiment derived from a plan) must not offer the delete of the thing they are
  derived from unless the confirmation says so.
- Rule: a test copy open in the operator's browser will be used as the real app. Say in the same message which port is the copy, keep it as
  near the real data as the task needs, and treat "something vanished from the copy" as a user action until the audit table and the UI paths to
  that delete show otherwise. The first move on "my data is gone" is: which instance, the audit of each, then the code path.


- Mistake (2026-10-20): explaining why a work had only 18 colours I wrote "565 colours belong to other lasers, lenses and titaniums" without
  looking. There was one laser, one lens and three titanium RECORDS; the work's own record held 18 and the other two plates of the same grade
  held 489 more. The operator had to ask "Каким другим лазерам и титанам?" and then answered that the plate does not matter, only titanium and grade.
- Rule: before explaining a number with a cause, query the data for that cause (here: group the points by device, lens and material record) and
  quote the counts. "Another X" is a claim about rows; check the rows.
- Rule: when the operator names what matters ("the material: titanium and grade, not the size"), put that definition in one function and
  test the neighbours of the boundary (same grade other case, other grade, other family, no grade), not only the case they described.

## A rule about how a value is derived is searched for at every place that derives it
- Situation (2026-10-20, REQ-045): "the colour of a setting" was the plain mean of its engravings in four places (knowledge `summarize`, the palette entry,
  the colour map search, the points of the map) and the confidence formula in two. Changing one would have left screens disagreeing on the same setting.
- Rule: before changing how a value is computed, grep every place that computes it (`np.mean` over engravings, `n / (n + K)`), put the rule in one pure
  function (`agreement.consensus`), call it from all of them, and list in the review the old tests that pinned the old rule and why they changed.

## A number shown for an area is checked against the area, region by region, darkest first
- Situation (2026-10-20, check 60): the layer list showed 16 colours that "do not match the photo, especially the dark ones". The earlier releases only checked the
  chart residual and the layer medians; nobody drew the shown colour next to the photo, element by element. C16's "colour" (L 55) matched none of its own elements
  (brown 47, grey-blue 69), and the whole plate had almost no pixel below L 45 because the correction had no offset.
- Rule: before releasing a measurement feature, render each reported colour as a fill beside the source photo and compare the darkest and the most saturated areas,
  and report the spread inside the area, not only its median. When the operator says "does not match", do this analysis first and quote numbers, not a re-explanation.

## "Why not just take it from the photo?" is answered by measuring the plain pipette first
- Situation (2026-10-20): the operator asked why the colour is not taken from the photo "like an eyedropper" and said the app lightens it. The answer I had (chart
  normalisation) was true but unmeasured for their picture. Measuring the plain eyedropper on the camera preview showed a 20 L* gap and that the lightening comes from the
  exposure normalisation, not from the matrix (exposure-only gives the same L).
- Rule: when the operator proposes the simple direct method, run it on their data next to mine, show both columns per item, say which part of the difference comes from which
  step (ablate: exposure only / matrix / offset), and say what remains undecided and who can decide it.

## When the operator says how the process should work, build their model first and measure mine against it
- Situation (2026-10-20): the operator said the work should go "the other way": know the 24 squares, take the colour like an eyedropper, find it among the squares, give it numbers
  - and asked why anything is lightened or darkened. I had defended one global matrix and then proposed a different shortcut (the camera preview). Their plain description, built and
  measured as a look-up among the squares, was better on exactly the dark squares they complained about (3.1 against 5.0 dE).
- Rule: when the operator describes the method in plain words, implement that description as the baseline, run it on their data in the same table as the current method, and then
  say which one wins and by how much. Do not propose a third method first.
- Also: an operator who says "it looks lighter" may be looking at a display default (gamma lift on top of an already corrected picture), not at the measurement. List every default
  view parameter of the screen they look at before touching the measurement.

## A copy of the database points at the real files
- Situation (2026-10-20): the pair rows hold absolute paths; a copy of the DB in the scratchpad pointed at `~/.titanium-platform/files`, so the rehearsal of "accept a revision"
  (which unlinks the superseded pair's files) would have deleted the operator's RAWs and LightBurn files.
- Rule: before running any mutating rehearsal on a copy of the data, copy `files/` too, rewrite every stored path to the copy (pair, plan, device_document) and verify with a query
  that no row still points at the real folder. Read-only analysis on a copy is fine; anything that accepts, deletes or purges is not until that check is done.

## A rule copied from documentation is a hypothesis about the operator's laser until the operator's own data agrees
- Situation (2026-10-20): "pulse width must be a step of the manufacturer's table" came from photographs of the laser documentation and was enforced everywhere; it silently pushed 138 of the
  operator's own observations (300 ns, 3, 5, 7, 8, 10 ns) out of the model, and when the re-measure kept two pairs for it I reported it as a fact about the laser. The operator: "Who said that?
  Of course it works - I entered it."
- Rule: when a refusal or exclusion rule comes from a document, first count how much of the operator's real data it excludes (a query by eligibility reason) and say so when the rule is introduced
  and whenever a result depends on it. Treat what the operator actually engraves as evidence about the laser, and ask before keeping a rule that contradicts it.

## A baseline that moves with every edit hides what the operator has not dealt with
- Situation (2026-10-20, work on the errors): the first design measured "colour drift" against the layers a work stored at its last edit. Any edit refreshes that snapshot for ALL layers, so
  applying one replacement would silently clear the marks of the other drifted layers. Found by thinking through "apply one of three proposals", not by a test.
- Rule: a mark that means "something changed since X" needs an X that only the operator's explicit act can move (here: making another file). Ask "which action resets this, and does it
  reset more than the thing the operator dealt with?" before choosing the baseline. A fixture shared by two source colours (yellow also used the paper recipe) exposed the same flaw in the test.
- Related: a threshold must be compared with the measurement's own error. 3.0 dE flagged 8 layers of the real work after the re-measure, all at 3.1-3.6 dE: the chart's honest error is 3.6.

## A fix that is deployed does not reach a page that is already open
- Situation (2026-10-20): the tab strip of a work clipped its sixth tab. I fixed the CSS, redeployed and reported, but the operator's open page still had the old CSS and sent a screenshot of the old layout.
- Rule: after a deploy that changes CSS or JS, say in the report "reload the page (Cmd+R)" for the screens that changed. Before calling a screenshot "still broken", reproduce it: probe the real work read-only in a separate headless profile, and inject the old CSS on a copy to see whether it gives the same picture.
- Again (2026-10-22, 0.22.0): «не могу перевести фото» - the operator's open tab of work 22 still ran 0.21.1 (no «Фото», no lasso) after the deploy and
  the report's "reload". Rule added: after a deploy that changes JS or CSS, read the version in the operator's open tabs of the app (read-only evaluate of
  the header); a tab on the old version is reloaded when it holds nothing unsaved (the editor saves every action; check the audit), otherwise the report
  names that tab and says to reload it. A banner "the app was updated, reload" in the app itself is the lasting fix - proposed, not built.

## A flag in the file is not proof of where a layer is: compare the files
- Situation (2026-10-20): the photograph of work 22 showed outlines on the ruler. The operator resized the picture in LightBurn; two layers were hidden, LightBurn's tools skipped them, and
  they stayed where the exported file had them. The check measured them at places where the photograph shows something else, and their rows (dE 24 and 46) looked like engraving errors.
- Rule: when an engraved file differs from the file the system exported, compare the geometry of the two before trusting any layer's position (scale, offset and mirror per axis, shared by most
  layers), and name a layer only when it provably sits at the old place while others sit at the new one. A "hidden" or "output off" flag alone says nothing about where the shapes are.
- Related: a layer that is not engraved must not become an observation with that recipe's settings; leave it out of the measurement and say so.

## A file for another program: write what it reads, never what it should assume
- Situation (2026-10-20): the operator opened the exported work in LightBurn and saw it upside down, with two straight slivers across the face. Two causes, both in the writer: the plates' flag
  (MirrorY) was not set for vector works, and four Bezier edges had a handle at one end only, written as "no handle"; LightBurn takes a missing handle for the origin of the shape, so each
  such edge swung to the top-left corner and back. Neither showed in our own tests: we parsed our own file with our own reader.
- Rule: for a file that another program opens, write every value that program reads (both handles of every curve, even when one lies on its vertex), and compare each header flag with the file
  of the same kind that is already known to work (the plates). Test it by reading the file back the way the other program does (a missing handle is the origin), not with our own parser's defaults.
- Related: a number is checked against the picture, not only against the file: the sliver's far end was computed from the missing handle (33.1, 42.8) and matched the screenshot (32.7, 42.9).

## A feature that exists in one place is not available where the operator works
- Situation (2026-10-20): the colour picker with confidence and basis existed in the work's table, but the editor, where the operator actually looks at the picture, offered only a merge box and
  "Исключить". The operator wrote "I cannot change colours so simply" and read "Исключить" as "this colour disappears".
- Rule: when a control exists on one screen, check the screen where the decision is made. Name a button by its effect on the output ("Не гравировать", with a hint that only the cleaning remains),
  not by an internal state ("exclude"). Show where a value comes from at the place it is chosen: one shared block, so the words are the same on every screen.

## A slow wait is the assistant's cost, not the operator's: parallelise the check and report the time honestly
- Remark (2026-10-21, voice-typed, during the 0.17.0 release): "Почему тесты занимают 30 часа" and then "Это глупо". The full suite (1494 tests) ran in one process for 14 min 15 s while the operator waited, and I had
  told them "11 minutes in, about 20 left" - I read the CPU-time column of `ps` as elapsed time. The real elapsed time was shorter and the end came sooner than I said.
- Rule: estimate the time left from the elapsed wall clock (`ps -o etime=`) and the percentage printed by pytest, never from the TIME column. When a check takes more than a few minutes, look for a way to run it
  in parallel before asking the operator to wait: `pytest-xdist` is in `.venv` (the operator approved it on 2026-10-21; it is in the `dev` extra, not in the app environment), so the release gate is
  `.venv/bin/python -m pytest -q -rs -n 12` (1494 tests in 2 min 32 s, none skipped). Adding a library still needs approval first.

## One found layer places all the others: do not let the file's on/off switches decide what the photograph can show
- Remarks (2026-10-21, voice-typed): "Не смог найти картинку" (a magenta frame far from the diploma), "достаточно найти один из слоев ... Важно, какой слой ты найдешь. НЕ важно", "ты можешь ориентироваться
  на линейку", "Это не просто линейка, а уголок". I had treated "output off" as "not on the plate" (REQ-050) and aligned by the largest picture of the layers that are on, which was a symmetric seal.
- Rule: every layer of a LightBurn file lies in one coordinate system, so an alignment needs evidence from any layer, not from the layer the file marks as on. Before designing a fix for a mismatch on a real pair,
  look at the photograph itself (an overlay, a crop) and test each assumption against the numbers: here a template match showed the "switched off" pictures are on the plate. A thing in the photograph that
  I named "a ruler" was a measuring angle: name what is there before choosing what to read from it.
- Rule: a prior from the scene (ruler scale) is checked on every real photograph before it is trusted: it was off by 2 on two of them (half-millimetre ticks) and in another plane on a framed plate, so the
  scale is tried as read, doubled and halved, and the match itself (several pictures agreeing) is the verification.

## Show everything the check found, not only what it measured
- Remark (2026-10-21, voice-typed, after 0.17.1): "В новой версии нашел только 1 картинку" with a screenshot of one frame on the seal. The check had found three pictures and placed every layer, and the overlay drew only the
  layer that is measured, because it skipped all layers left out of the measurement (REQ-050). I had judged the release by the numbers of the check and by the one frame that was measured.
- Rule: when a feature finds or places something, the picture the operator looks at must show all of it, with a style that tells "found, not measured" from "measured". After a fix, open the overlay on the real pair
  and count what is drawn against what the report says was found, not only the report. A sentence in a note ("was not engraved") must be checked against the photograph when the same check found the layer on it.
- Remark (same day): "Мне непонятно почему я не вижу версию апликации в header?" - the version existed only in `GET /api/version` (DEC-023). A fact the operator needs after every deploy (which release is running) belongs on the
  screen, not only in the API: when a deploy step says "tell the operator to reload", check that the operator can see what they are looking at.

## A changed drawing needs a new render version, and a deploy is checked by fetching the picture, not by the code
- Situation (2026-10-21, release 0.17.2): I changed what `_draw_overlay` draws and did not bump `render_cache.RENDER_VERSION` ("bump whenever the drawing of a cached picture changes"). The deployed server returned the
  picture it had cached under 0.17.1 (a GET took 0.01 s and the file had no light-blue pixel); the operator would have reloaded and seen no change. I found it only because the timing of the check GET was too fast.
- Rule: any change to what a cached picture shows (overlay, photograph preview, thumbnails) bumps `RENDER_VERSION` in the same commit. After a deploy that changes a picture, download that picture from the running server
  and count what must be in it (colour pixels, outlines); a response that is much faster than a drawing takes is a cached one.


## Ask the operator for facts only he has, not for the method; then tie his number to the exact artefact
- Remark (2026-10-21, voice-typed, release 0.18.0): asked how the time model should learn ("record real times" / "fix the reader only" / "fit now"), the operator answered "Понимаю, в чём проблема
  рассчитать, когда ты знаешь скорость, расстояние между линиями, частоту ... и площадь? ... около трёх часов, но не полтора часа точно". Then: "я модернизировал это на 100 на 100 миллиметров, не 150
  на 150. 150 на 150 занимало где-то около трех часов. 100 на 100 ... полтора часа, около двух".
- Rule: when a measured number disagrees with the model, first find which file, size and settings the number belongs to (the work existed as three files: 150 mm and two at 100 mm) and show the
  operator those facts; ask him only what he alone knows (which job, how long). Choosing the method (count pieces of scan line from the geometry, fit one cost to his jobs) is my job, and the
  physics plus his two numbers settled it: 1 ms per piece fits both sizes, 0.3 ms per 10 mm line fitted the 150 mm job only by chance.

## Two estimates of the same thing that disagree are a bug report: find why before shipping either
- Situation (2026-10-21): the new time of a work from its LightBurn file (1 h 10 min) disagreed with the vector screen (2 h 59 min). The cause was in the reader, not in the time: LightBurn writes a
  path's VertList / PrimList once and later paths name it by VertID / PrimID; 222 of 574 paths were read as open lines with no area, in 8 stored files (DEC-102), so areas, overlays and
  measurements of those works had missed shapes since the start.
- Rule: when I add a second way to compute a number the platform already shows, compare the two on the operator's real data before release; a gap is traced to its cause (here: count closed vs
  open regions per file) instead of being explained away by "different models".

## A picture written for LightBurn is checked by reading it back, not by its tags
- Situation (2026-10-21): the Image-layer writer copied every tag of the operator's real files but stored the picture top row first; LightBurn stores Image pictures bottom row first (the operator's
  Motorcycle PNG is upside down under a positive XForm), so every downloaded file would have engraved upside down.
- Rule: a writer of an existing format is tested by a round trip through the same reader that reads the operator's real files, comparing the result pixel by pixel with what was uploaded, and the
  reader's convention is checked on a real file first.

## Bulk edits go through a script over source files, and spec ids come from MarkView before they go into code
- Situation (2026-10-21): code cited REQ-058 for photo engraving, but requirement ids are global across MarkView features and REQ-058 was vector-detail's. Renumbering with `sed` over `grep -rl`
  hit `__pycache__/*.pyc` (grep lists binary files; sed stopped half-way with "illegal byte sequence"), and an unquoted `$FILES` is one word in zsh.
- Rule: add the requirement or decision with the MarkView tool first and cite the id it returns. Rename across files with a Python script over text files only (`*.py`, `*.js`, `*.css`), deciding
  the new id line by line by meaning, then grep the result for every old and new id.

## An isolated copy of the data is isolated only when its file paths point into the copy
- Situation (2026-10-22): to reproduce the check of the plate's photo I copied the database and the files folder to the scratchpad and ran `remeasure_pair` on the copy. The copy's
  pairs still held absolute paths into `~/.titanium-platform/files`: the revision's files were written there, and accepting it on the copy deleted the operator's own `.lbrn2` and DNG of
  pair 107 from the live folder. Restored byte-identical from the copy taken two minutes before (21 pairs checked, none missing); the live database was never written.
- Rule: right after copying, rewrite every path column of the copy (`pair.lightburn_path`, `pair.photo_path`, and any other stored path) to the copy's folder and assert that no path
  of the copy starts with the live data folder, before running anything that can create, accept, revise or delete. Compare the live files folder with its copy after every such run.

## A new kind of layer on a plate is tested with the file as LightBurn saves it back, not only with our export
- Situation (2026-10-22): the grey-ramp plate (the first plate with Image layers) passed every test with our own export, but the operator engraves from the file LightBurn 2.2 saved again:
  `MirrorY` rewritten with the XForms reflected, and a picture placed twice stored once (`Data=""`, the same `SourceHash`, another file name). Three tiles read "0 pixels", four had no picture.
- Rule: when a plate or writer adds a new kind of shape (pictures, holes, groups, texts), add a test that round-trips the file through LightBurn's saving habits (`saved_by_lightburn_2_2` in
  `tests/test_grey_scales.py`, the MirrorY reflection in `tests/test_ingest.py`) and measures it, and make every transform of a shape (outline, holes, the picture's matrix) go through one place.

## What the operator entered lives above any panel that is rebuilt on a choice
- Situation (2026-10-22): on the photo engraving screen each scale panel built its own picture block, so choosing another scale threw away the picture the operator had chosen
  ("когда я выбираю картинку, а потом меняю шкалу, то он картинку удаляет"). The tests checked one scale at a time and never switched.
- Rule: input that does not depend on the choice (a file, a width, a checkbox) is owned by the screen and handed to the rebuilt panel; a UI test of a screen with a list of choices
  switches the choice after entering something and checks it is still there and re-used.

## The next physical experiment is written as screen steps: what to press, what stays the same, what changes, and why
- Situation (2026-10-22): I described the next experiment as "one picture, two sizes on the plate scale"; the operator downloaded the plate's file again, saw the same speed and asked
  what to re-engrave. The plate was not to be re-engraved: a picture was to be engraved twice at two widths with the plate's settings.
- Rule: every experiment I ask for names the screen, the fields with their values, the files to download, what to engrave, what is unchanged from before and the one thing that changes,
  in numbered steps; never only a short name of the experiment.

## A one-screen page uses the whole window, and every column and tab is checked for cut text at the operator's real width
- Situation (2026-10-22): the one-screen photo engraving kept `.main {max-width:1440px}`, so on the operator's 1771 px window it stood in the middle with empty sides while the
  right table (506 px) had 374 px and the subtitle ended in "…" ("расширяй до конца - не помещаются надписи"). I had looked at one tab at one width only.
- Rule: a `.os` page has no width cap (the shared rule `.main:has(>.os)`). Before showing a one-screen page, read the window width of the operator's tab, and for that width and for
  1372 px walk every tab of every column: no element may scroll sideways or end in an ellipsis. A wide table in a narrow side panel becomes a list of entries.

## "Like the other section" means its whole structure, not only its layout
- Situation (2026-10-22): asked to make photo engraving "на один экран, так же как и все другие", I turned the reference screen of scales into one screen. The operator meant what the
  vector section is: saved works, a list of them, open, copy, rename, delete, and a one-screen workspace for one work ("мне нужны работы, так же как и в векторной гравировке").
- Rule: when the operator compares a section with another one, list what the other one has (its entry screen, what it stores, its actions, its workspace) and confirm which of them are
  meant before building; the layout alone is rarely the whole request.

## A work the operator edits gets undo and redo for every change, and an AI that builds on its last answer also gets a way to start again
- Situation (2026-10-22): 0.19.1 gave the photo work an AI that proposes rules for the parts of the picture. Each new request was sent with the current rules, so the answers built
  on one another, and the only way back was «Вернуть как было», one step over the last answer. After four requests the operator could not get back to the plain picture, deleted
  the work and made a new one ("Нет возможности перегенерировать с картинки, отменить действие"). The vector editor had had «Отменить» / «Повторить» for every change since DEC-077.
- Rule: every editable work keeps undo and redo of every change that alters what it engraves (server side, as the vector editor does, with the buttons and Ctrl+Z / Ctrl+Shift+Z);
  an AI request that refines the present state also has a way to start from the original. Before releasing an editing screen, check it against the vector editor: what can be
  undone there must be undoable here.

## A synthetic test of a measurement uses data shaped like the real material, and a new path is walked on a copy of the real data before release
- Situation (2026-10-22): the end-to-end test of 0.19.3 drew the photograph from the test scale, whose colours happen to darken with the grey; it passed at once. On a copy of
  the operator's data the same photograph drawn from work 28's real scale (150 mm/s, 1-30 %, colours that rise and fall along the power) was read upside down and dropped as
  "weak": the free-picture measurement guessed the orientation from the order of lightness. The same walk found the analysis page, the experiment page and the mode name broken
  for a photo-work pair, a path no test had opened.
- Rule: a measurement test includes data shaped like the real material (for titanium: colours that do not darken step by step), and before release every screen a new kind of
  record reaches (check, analysis, experiment, upload) is opened on a copy of the real data with a simulated record, not only the screen that was built.

## On an isolated copy, touch only records the copy created
- Situation (2026-10-22): the copy of the database keeps the old pairs' file paths in the operator's folder (`~/.titanium-platform/files`); deleting or re-measuring such a pair
  on the copy would delete the operator's original files. During the check a pair and work 28 on the copy were deleted through «Удалить эксперимент» (cause not established).
- Rule: on a copy, delete, re-measure or change only records made on that copy (check their file paths first); before touching any record, read its paths read-only. In a browser
  script never set `location.href` (it reloads the page and the script never returns); navigate with the browser tool and read in a separate call.

## A measurement predicts only the conditions it was made under: record them, and say on screen when a prediction is used outside them
Operator, 2026-10-22: "цвета дичайше меняются ... в зависимости от размера картинки ... черный на лбу не должен быть черным ... ты неправильно выбрал". The scale of the
work was measured on 38.4 mm ramps and used for a picture stretched to 150 mm; at 150 mm the first oxide colours came at higher power (median 14 dE apart), so the
preview promised colours the plate could not give. The same file drawn with the colours measured at 150 mm matched the engraving (median 4.9 dE per pixel).
- Every colour measurement keeps the conditions that move colour (here the scanned row length, i.e. the size); a prediction says which conditions it was measured under and
  warns when the work is outside them, instead of silently using the nearest scale.
- A per-pixel "nearest colour" choice is not a drawing: it can put neighbouring skin tones in different regimes of the scale (black forehead) and give the lips the
  skin's grey. Keep the picture's light and dark in order and check that every edge of the picture survives in the predicted engraving.
- Before saying "the colours are wrong", draw the engraved file through the colours measured at the engraved size: it separates a wrong scale from a wrong choice.

## A default that changes the engraved picture is walked in every mode and on every scale it reaches, not only the case that asked for it
Operator, 2026-10-22, after 0.20.1: "какие-то белые секции делает непонятные, очень неприятно ... раньше этого не было". Contours were made for the colour choice that
keeps the drawing and walked only there (0.04 % of «Inna Portrait»), but they were on by default for every work, the plain picture too. On a scale whose colours are all
dark every edge counts as lost and was drawn in the lightest grey: white dashes over up to 3.7 % of the picture, on the operator's own picture as LightBurn sees it.
- Before turning on by default anything that adds to or changes the greys of a file, run it on every scale of the operator's data and in every mode (plain picture,
  picked greys, rules) and look at the pictures, not only the share.
- The plain picture «как её видит LightBurn» is the operator's own picture: nothing is added to it unless the operator asks for it.
- A line drawn only where a test fails along an edge breaks into dashes wherever the test flickers; a line is either the whole edge or none.

## The operator's examples decide the scope of a request: objects named one by one mean a choice per object
Operator, 2026-10-22: "общую тональность ... столб сзади в синей тональности, кожа светлее, очки красные ... не напрямую, а основной цвет, вокруг которого всё
строилось бы". I read "основной цвет" as one colour for the whole picture and prototyped a global tone; the operator: "Мне нужно не общий цвет менять ... отдельно
разукрасить губы ... очки ... как в разукрашке". "Не напрямую" was about how a colour is given (a range of the scale around it, not one fixed grey), not about scope.
- Rule: when the operator illustrates a wish with several objects that get different colours, the request is per object. Before prototyping, restate the scope
  with their own examples ("фон синий, кожа светлее, очки красные - каждый объект свой цвет?") and prototype that.

## A record named after a physical thing is not automatically the identity of what is measured
Operator, 2026-10-22, on the preview refusing «Small Plate» for a mode measured on «Big Plate 150»: "должно работать для титана любого размера". Every
measurement was partitioned by the plate record (`material_id`), so two plates of one titanium never shared a scale. The operator: every Grade 5 plate is one
titanium; size, thickness and batch do not matter.
- Rule: when a key partitions measurements (plate, laser, lens, size ...), check with the operator what makes two records the same for the colour, before a
  second record of the same kind appears; say on screen which records a prediction pools.

## Every file the platform writes for engraving on titanium is checked against the others for what they all carry
Operator, 2026-10-22: "когда генеришь LightBurn file - не забывай про cleaning layer". Plates and vector works clean first on C00; the photo work's file was
written "like the operator's own photo files" with the picture alone, so the work would be engraved on uncleaned titanium while its scale was measured on cleaned
plates.
- Rule: a new export path lists what every other export writes (the cleaning first, markers, the identifier in Notes, the run order) and either writes it or says
  in its docstring and on screen why not; the conditions of the measurement the prediction rests on (cleaned plate) are the conditions of the file.

## A test in a shared world asserts what it changed, not what the world holds
Twice (0.20.0 `others == 2`, 0.20.3 `others == 1`) a test of `test_photo_work_engravings` passed alone and failed in the full suite: the module's plate world is
shared, so earlier tests' works are engravings of the same scale too.
- Rule: in a module- or session-scoped fixture, count before and after (`after == before + 1`) or assert a bound (`>= 1`); an exact count only of what the test
  itself made. Run the new test with its whole module before the full suite.

## Every release report says what of the operator's goal is still not built
Operator, 2026-10-22: "где вот это изменение, которое я тебе давно просил ... какую конкретно ты хочешь делать гравировку ... grayscale или какую-то другую".
The first goal of photo engraving named many kinds; only grayscale works were built, and no report said that the other kinds were still missing.
- Rule: a release report ends with the parts of the operator's standing goals that are not built yet, in one line each; a scope narrowed for a release
  ("grayscale first") is written into `tasks/todo.md` as an open item, never left implicit.

## Say what an existing work will and will not show after a release
Operator, 2026-10-22: "Я открыл существующую Boris3 работу, и там ничего не поменялось". 0.20.3 changed the file, the time and labels, not the picture; the object
colouring was a prototype on a scratch page.
- Rule: the report names, for the operator's own works, what changes on screen and what stays the same and why; a prototype is called a prototype, with
  where to look, and never mixed into "what is new in the app".

## A question the operator expects at a click is visible at that click
Operator, 2026-10-22, after 0.21.0: "Почему при фотографировке, когда я выбираю новую работу, он не спрашивает меня, какую фотографировку я хочу сделать?"
«Новая работа» opened the old dialog (picture, name, width); «Какая гравировка?» opened only after «Создать», promised in grey small print. The walk opened
the question from the «Вид» button and never clicked «Новая работа» as the operator would; the operator deleted Boris - 3 and stopped at the dialog.
- Rule: when the operator says "when I choose X it should ask Y", Y is on screen the moment X is chosen (its first step), not after a later button.
- Rule: walk every new flow from the operator's own entry point (here «Новая работа» on «Мои работы»), click by click, before the release.

## A set of regions is shown as one shape
Operator, 2026-10-22, after 0.22.0: «пусть он все выделения как-то обозначает ... желтым ... не каждую часть, а общее ... объединять его одно.»
A selection (and a zone, and a hover) outlined every region on its own: 108 thin yellow outlines for one face, lost on the cream colours.
- Rule: whatever the operator picks as one thing (a selection, a zone, a layer under the pointer) is drawn as one outline - the borders with the set on
  one side only - on a dark halo so it shows on light and dark colours. Per-region marks are for per-region facts only (the far colours).

## A new kind of layer appears on every screen that lists the layers
- Mistake (2026-10-22, 0.22.0): the photo zone's Image layer reached the file, the editor's «Слои», the work's «Файл» tab and the header counts, but
  not «План гравировки», which lists the layers and exports the same file. Found only when the goal was re-checked.
- Rule: when the file gets a new kind of layer, grep every screen that lists layers (`layers.map`, `p.layers`, layer tables) and every count of them,
  and walk each on a copy with the new layer present before the release.

## A tab that asks for an action on the picture switches the picture to that action
- Mistake (2026-10-22, 0.22.0): «Фото» told the operator to select regions, but the selection tool and the selection's buttons were on «Кисть»; on
  «Фото» a click repainted with the brush. The operator: «Не выбирается».
- Rule: when a panel tab's work starts with a click on the picture, opening the tab sets the tool for it, and the buttons that act on the result
  are on that tab. Walk the flow from the tab itself, starting with the tool the operator last left.

## Escape works from anywhere a key means nothing else
- Mistake (2026-10-22): the editor's "a field has the focus - leave the keys to it" rule covered Escape too, so after a power field, a checkbox
  or the slider Escape did nothing. The operator: «Когда нажимаешь Escape, выделения должны уходить.»
- Rule: guard only the keys a field uses (typing, Ctrl+Z, space); Escape drops the selection and everything drawn for it except in an open dialog.


## A prediction says what it rests on before the operator engraves by it
- Mistake (2026-10-23): the photo work showed the look of a 150 mm portrait from the nearest measured size (a 100 mm portrait on another,
  uncleaned plate) without a word; the result was 18.7 dE off and much lighter. The operator: «когда ты предлагал мне вариант, он выглядел
  намного темнее, чем сейчас».
- Rule: whenever a prediction is made from another size, another plate or another cleaning, say so where the prediction is shown, with the
  expected error from the reviews (DEC-117); and check a new model change against the reviews' median before keeping it.

## A box that turns a click into a fraction must be the picture's box
- Mistake (found 2026-10-23, pair 113): the corner editor took fractions of its .photo frame, which a flex column stretched wider than the
  photograph; the dots were drawn in the same frame, so they looked right while the server got every corner squeezed to the left. The
  operator: «Мне кажется он не правильно углы подставляет».
- Rule: wherever a pointer position becomes a fraction or a picture coordinate, check in the browser at the operator's window width that
  the measured box equals the picture's box (getBoundingClientRect of both), not only that the dot appears under the pointer.

## When outlines miss the photograph, compare the engraved file with the export before the alignment
- Mistake (2026-10-23, pair 115): the outlines of two layers lay below the plate; the alignment was right (0.1 mm), the engraved file had
  those layers 60 mm wide at the old place because the export hid them and LightBurn's tools skip hidden layers. The operator: «Почему
  вообще за пределы линейки что-то выходит? ... Как такое может быть?»
- Rule: first diff the uploaded .lbrn2 against the work's exports layer by layer (bounds, XForms, hide/doOutput, MirrorX/Y); a file
  LightBurn re-saved reflects every shape, hidden ones too, so compare files as LightBurn saved them, before any turning to the plan's axes.

## Name a browser tab by its full name, never by a number
- Mistake (2026-10-23): `tab: "3"` in the MarkView browser tools picked the operator's App tab, not the third tab in the list, and the
  copy's page (8791) opened in it over the operator's `#/experiment/plan-39`; it was put back at once.
- Rule: pass the tab's full name as browser_tabs prints it (for the copy: «ТЕСТ: копия данных, порт 8791 (не настоящее приложение)»);
  never a number or a fragment that could match another tab, and check the tool's answer names the tab meant before the next step.

## Check the physical scale on the photograph before saying which file was engraved
Pair 116: I concluded that the loaded file (scaled to 89% x 85% of the export) was not the engraved one because the export's contours
fitted the photograph and the file's did not. Wrong: the alignment maps the photograph's markers to the PLAN's positions (164 mm apart),
so the whole photo space is stretched by 1/0.89, and a plate engraved from the scaled file looks like the export in that space. The
ruler in the photograph (20.2 px/mm) gave the markers 143 mm apart: the scaled file was engraved, the app's assumption was wrong.
Rule: before blaming the operator's file, measure an absolute length on the photograph (ruler, marker size, plate width) in pixels and
compare it with both candidates; a homography fitted to 4 markers absorbs any scale and proves nothing about size.

## Add files to git by name, never a directory
`git add docs/features` swept in the untracked `docs/features/electron/`, which is not ours, and it went to main in a7531b4 (untracked
again in the next commit). Add the exact files a tool or an edit produced; check `git status --short` for `??` entries before committing.

## A capability postponed again and again reaches the operator as "I can't"
- Situation (2026-10-24): «Цвет с карты» for photo zones (D6 of 0.25.0) was moved to the next release four times; the operator, on a zone
  whose only scale is nearly black, wrote «я не могу выбрать цвет … ничего такого сделать не могу».
- Rule: a feature promised for "the next release" twice is either built in the next one or written in the release report as not built, with
  what the operator can do meanwhile (here: switch the zone's scale); never carried silently a third time.

## Comments are in English, also in a file whose comments are Russian (0.28.0, 2026-10-24)

- The operator's global rule is "always English in files or comments". The UI scripts carry many Russian comments from earlier releases;
  matching them is not a reason to write new Russian comments. In 0.28.0 thirty new comments in seven UI files were written in Russian
  and had to be translated afterwards (commit "chore(ui): the comments added in 0.28.0 ... are in English").
- Rule: every new or rewritten comment, docstring and JSDoc is English, whatever the file around it. Russian stays only in strings the
  operator reads on the screen and in the translations. Before a commit, grep the added lines of the diff for Cyrillic inside `//`, `/*`
  and `*` comment lines.

## 2026-10-24 — a sign-in design built on a fake of the provider (electron, DEC-058 → DEC-060)

- **Pattern.** The handoff sign-in was designed, built and merged against a fake Neon Auth that accepted a bare session token as a
  cookie. The real service accepts only its HMAC-signed HttpOnly cookie, so the design could not work, and the deployed API ran it for
  an afternoon. Found only by an end-to-end emulation against production after the merge.
- **Rule.** Before designing anything against a third-party auth or API, probe the real service for the exact calls the design relies on
  (here: `GET /token` with the value a page can actually read) and record the answers in the spec note; a fake may only mirror what was
  observed, never what the docs seem to promise. Make the production emulation part of the stage's definition of done, not an afterthought.
- **Deploy.** The wheel of this project is `titanium_color_engraving_platform-<v>-py3-none-any.whl` (the distribution name, not the
  import name); the live database is `~/.titanium-platform/titanium.sqlite` (other `*.sqlite*` files there are empty leftovers). Take the
  file by name, never by a glob with `head -1`, and check the backup's size before restarting the server.
- **Build.** The core's `__version__` comes from the package metadata; the editable install in `.venv` keeps the metadata of the
  version at install time (it said 0.3.1 while `pyproject.toml` said 0.31.0), so a PyInstaller build from the venv reports the old
  version. Before a desktop build: `uv pip install --python .venv/bin/python -e . --no-deps` (the venv has no pip), and read the version
  in the core's smoke line, not only `"smoke": "ok"`.

## A wheel built before the desktop core leaves an egg-info the core then carries (0.32.0, 2026-10-24)

- **What happened.** `python -m build --wheel` ran first and left `src/titanium_color_engraving_platform.egg-info` (git-ignored, so
  `git status` does not show it). PyInstaller then bundled that egg-info instead of the editable install's dist-info; the core's smoke
  still said 0.32.0, but `desktop/forge.config.js` looks for a dist-info and refused the package ("the built core says null").
- **Second source.** `uv pip install --python .venv/bin/python -e . --no-deps` (the step that refreshes the version) writes the same
  `src/*.egg-info` while it builds the editable wheel, and the spec runs with `PYTHONPATH=../src`, where importlib finds it first.
- **Rule.** Remove `src/*.egg-info` immediately before PyInstaller (after the editable refresh and after any wheel), build the core and
  the shell, the wheel last; check that `dist/titanium-core/_internal` holds `titanium_color_engraving_platform-<v>.dist-info`.
- **Third trap (0.34.0).** The shell is zsh: `rm -rf src/*.egg-info && …` with no egg-info present fails on the unmatched glob, the
  `&&` chain stops before PyInstaller, and the smoke that follows runs the previous core (it said 0.33.0). Remove it with
  `find src -maxdepth 1 -name "*.egg-info" -exec rm -rf {} +` and read the version the smoke prints before going on.

## Look at the picture a plate will engrave before handing the plate over (0.32.0, 2026-10-24)

- **What happened.** The variations plate cut its copies from the window of the zone's picture with the widest grey spread; on the
  real zone (a portrait with sunglasses) that was the inside of a dark lens with greys 32–150 only, useless for judging a portrait's tones.
  Seen only by rendering the window from a copy of the live database.
- **Rule.** Before a plate built from the operator's own picture is handed over, build it on a copy of the live database and look at the
  picture each copy engraves; a selection rule tested on synthetic pictures is not proven on a real one.

## Tick an acceptance criterion only against its own words (0.33.0, 2026-10-24)

- **What happened.** REQ-004 (approved) says a step changes "the setting with the largest measured effect"; the step was built to take
  the setting measured on the most photographs first. Found only when the criteria were read one by one before ticking them.
- **Rule.** Before ticking a criterion, read it word by word against the code path and a test that shows exactly that behaviour. A
  design reason to differ goes into a proposed decision and the code follows the approved text until the operator accepts the change.

## A shared panel added to a screen needs every harness of that screen updated (0.33.0, 2026-10-24)

- **What happened.** The photo work's advice panel (`PhotoQuality.advisor`) broke four lettering tests: they reuse the photo work's node
  harness with their own data, which had no `advice` answer, and the panel read a missing answer. Module-level `App.toast/go/fail`
  were also undefined where `photo-quality.js` loads (before `dialogs.js` and `router.js`), and tests replace `App.go`.
- **Rule.** A new script goes into every node harness that loads its screen (grep the screen's name in `tests/`); every new GET it makes
  gets a fake answer in each harness's data; helpers that join `App` later are taken when used, not destructured at load.

## Two tables are named for a device (0.33.0, 2026-10-24)

- **What happened.** A query joined `device` for the laser's name and returned nothing: `device` holds the sync tokens of
  devices; lasers are `laser_device` (what `pair.device_id` references).
- **Rule.** Read the `REFERENCES` of the column in `db.py` before joining on it.

## No long lists: every list is compact and manageable (operator, 2026-10-25)

- **What happened.** The «Выводы» screen showed every finding of a run as a full card, one after another: 103 cards (45 anomalies,
  32 questioned entries, …), then the photo-engraving section below them. The operator could not delete, change or sort them, could
  not see what mattered, and never scrolled to the bottom. Nor could they re-check all existing works after the measurement changed.
- **Rule.** A screen that lists many items shows one compact row per item or per group (with a count), details on demand, sorting,
  filters, paging and per-item actions. Its default view shows what still needs attention. Count the items a screen would show on the
  live data before shipping it. Anything derived from the measurement gets a way to re-derive it for everything already accepted.

## The audit table of a "no long lists" round misses lists: sweep the screens on the live data (0.34.0, 2026-10-25)

- **What happened.** The plan's table named the long lists found by reading the screens' code; four agents converted every one of them
  and their tests passed. A sweep of the screens on a copy of the live workshop (every container with more than 25 visible children)
  then found two more: «Состав работы» of a matrix experiment (a 100-row table in `composition.js`, a module no agent owned) and the
  vector editor's palette (639 squares, 1787 px of scrolling in a 281 px column).
- **Rule.** Before calling a screen free of long lists, open every screen on a copy of the live data and count the visible children
  of every container (script in the browser, `location.hash` per screen, results kept in `window` and read afterwards: one call that
  awaits the whole sweep times out after 45 s). Shared modules that several screens embed (`composition.js`) go into somebody's brief.

## Comments are in English: the second time (0.34.0, 2026-10-25)

- **What happened.** The rule of 0.28.0 was broken again: new Russian comments in `list.js` and `findings.js` (mine, rewritten before
  the release) and in seven other files from the four agents (mixed «Карточка … The layers are …» JSDoc, a translated comment moved
  with its line). The agents' briefs did not repeat the rule.
- **Rule.** Every agent brief that writes code says "comments, docstrings and JSDoc in English, also where the file's old comments are
  Russian". Before the commit, scan the added comment lines of the diff and the new files for Cyrillic outside «…» quotes.

## Tick an acceptance criterion only against its own words: the second time (0.34.0, 2026-10-25)

- **What happened.** REQ-002 says the chips «Требуют внимания · Учтённые · Скрытые · Все» show their counts; `App.list` hid the chips
  at zero, so «Учтённые» and «Скрытые» did not exist until something was marked. REQ-003 says each row has «Заметка»; the note was only
  inside the opened row. Both were found while reading the criteria one by one before ticking them, after the suite had passed.
- **Rule.** As in 0.33.0, and earlier: read the criteria word by word while building the screen, not only before ticking; a missing
  button or chip is cheaper to add then than after the release suite.

