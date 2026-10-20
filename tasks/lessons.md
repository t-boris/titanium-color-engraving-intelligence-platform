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

## A flag in the file is not proof of where a layer is: compare the files
- Situation (2026-10-20): the photograph of work 22 showed outlines on the ruler. The operator resized the picture in LightBurn; two layers were hidden, LightBurn's tools skipped them, and
  they stayed where the exported file had them. The check measured them at places where the photograph shows something else, and their rows (dE 24 and 46) looked like engraving errors.
- Rule: when an engraved file differs from the file the system exported, compare the geometry of the two before trusting any layer's position (scale, offset and mirror per axis, shared by most
  layers), and name a layer only when it provably sits at the old place while others sit at the new one. A "hidden" or "output off" flag alone says nothing about where the shapes are.
- Related: a layer that is not engraved must not become an observation with that recipe's settings; leave it out of the measurement and say so.
