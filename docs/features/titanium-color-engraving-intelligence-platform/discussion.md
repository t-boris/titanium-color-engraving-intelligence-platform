# Discussion — Titanium Color Engraving Intelligence Platform

### Answer to Q-001 · 2026-10-14

Для кого система в первой версии: кто за ней сидит и чьи данные она накапливает?

A. Один исследователь/мастер (вы) с одним лазером — личный лабораторный инструмент.

### Answer to Q-002 · 2026-10-14

Что первая версия должна уметь «от начала до конца», чтобы считаться готовой?

C. Калибровочный цикл + оба режима гравировки + Experiment Designer (всё заявленное).

### Answer to Q-003 · 2026-10-14

Чем фотографируются/измеряются платы в первой версии и что служит цветовым эталоном?

B. Фиксированная установка: камера на стойке, контролируемый свет и угол, эталонная карта в кадре, RAW.

### Answer to Q-004 · 2026-10-14

Какого рода приложение вы видите: где оно живёт и как с ним работают?

B. Локально запускаемое веб-приложение (один процесс на ПК, интерфейс в браузере).

### Answer to Q-005 · 2026-10-14

Какой лазер и какое пространство параметров фиксируем для первой версии?

A. Один конкретный лазер (например, ваш fiber/MOPA) и фиксированный набор осей: мощность, частота, скорость; остальное (длительность импульса, интервал линий, проходы, фокус) — константы профиля.

### Answer to Q-006 · 2026-10-14

Как знание переходит из «validated» в «production»: кто принимает решение и какой минимальный порог повторов?

C. Автопродвижение до «validated», ручное — в «production».

### Answer to Q-007 · 2026-10-14

Что считается успехом в Continuous Photo Engraving: тональная (яркостная) точность фотографии или управляемый «переливающийся» цветовой путь

C. Оба как два под-режима с общим пайплайном.

### Answer to Q-008 · 2026-10-14

Как непрерывно меняющиеся параметры должны попадать в LightBurn, учитывая, что он задаёт параметры по слоям, а попиксельно умеет менять толь

B. Квантование изображения на N полос, каждая — отдельный слой LightBurn со своим набором параметров (мощность, частота, скорость).

### Answer to Q-009 · 2026-10-14

Как система должна поступать в Discrete Color Engraving, когда желаемый цвет изображения не попадает ни в один validated/production цвет тит

C. Как B, плюс недостижимые цвета автоматически передаются Experiment Designer как цель для следующей калибровочной платы.

### Answer to Q-010 · 2026-10-14

Должны ли «боевые» гравировки (арт и фото), а не только калибровочные платы, нести registration markers и идентификатор плана, чтобы пост-ан

B. Опционально на уровне плана: с маркерами — автовыравнивание, без них — ручное выравнивание по углам изображения в UI.

### Answer to Q-011 · 2026-10-14

Что система должна делать с цветом в статусе production, если новые наблюдения (пост-анализ или повторная плата) показывают, что он нестабил

B. Как A, плюс цвет «под вопросом» по умолчанию исключается из новых планов (с возможностью явно включить), пока пользователь не подтвердит или не понизит его.

### Boris Tsekinovsky · 2026-10-14

Я хотел бы, чтобы я мог иметь возможность, скажем так, прикрепить, ну, скажем, lightburn файл и прикрепить фотографию уже готовой картины. И он должен мне понять цвета, понять стабильность и все остальное. То есть я могу сейчас почти для каждой картины, которая у меня есть, прислать еще lightburn, чтобы он начал понимать и цвета в том числе. Кроме как просто фотографии с матрицей цветов.

### AI · 2026-10-14

Понял: вы хотите импорт «исторических» гравировок — пара «файл LightBurn (.lbrn/.lbrn2) + фото готовой работы» — как ещё один источник данных для модели, помимо калибровочных плат. Это хорошо ложится в закрытый цикл: по сути это Post-Engraving Analysis для планов, которые система не генерировала.

**Что это даёт (моя оценка, не факт):**
- Файл LightBurn — XML; из него извлекаются слои с power/speed/frequency и геометрия заливок → можно восстановить «план» без вашего участия.
- Каждая область слоя на фото становится наблюдением «параметры → цвет», причём сразу на реальных работах.

**Где я вижу проблемы — нужны ваши ответы:**

1. **Доверие к таким данным.** Старые фото сняты не на стенде, без эталонной карты, возможно при другом фокусе/партии титана. Как считать такие наблюдения?
   - A. Отдельный уровень провенанса «legacy/uncontrolled»: попадают в базу, участвуют в карте цветов как «подсказки», но не засчитываются в повторы для продвижения до validated — его подтверждают только стендовые платы.
   - B. Обычные наблюдения с пониженным весом / повышенной ошибкой.
   - C. Только как цели для Experiment Designer.
   Предлагаю **A** — не нарушает принцип «измерения как источник истины».

2. **Выравнивание.** Маркеров нет → ручная привязка по углам в UI (DEC-010). Достаточно для десятков работ, или нужен полуавтомат (сопоставление контуров из файла с фото)?

3. **Недостающий контекст.** При импорте спрашивать минимум: профиль лазера, примерная дата, тот же ли фокус и материал? Или «неизвестно» по умолчанию?

4. **Стабильность из одной работы не выводится** — только из повторов одних и тех же параметров в разных работах. Подтвердите, что ожидание именно такое.

Ответьте хотя бы на п.1 — остальное могу предложить сам.

### Boris Tsekinovsky · 2026-10-14

About this fact from SRC-001: "Laser parameters of interest include at least power and frequency; other parameters (speed, focus, hatch, passes) are implied by the mention of focus and environment variability." — is it right, and what does it mean for the feature?

### AI · 2026-10-14

**Коротко: факт наполовину верен, наполовину — натяжка, и он уже перекрыт DEC-005.**

**Что действительно есть в SRC-001 (факт):**
- Power и Frequency упомянуты — но только как *пример* («эта клетка соответствует Power X / Frequency Y»), а не как определение набора параметров.
- Слов «speed», «focus», «hatch», «passes» в вашем исходном тексте **нет**. Фраза «material batch, laser, focus and environment» — из раздела Problem, который написан мной как пересказ, а не ваша формулировка.

**Что в факте — вывод, а не факт (моя оценка):** вторая половина («implied by the mention of focus…») — AI-инференс, построенный на моём же пересказе. Его стоит переформулировать: *«SRC-001 names power and frequency as an example of grid axes; the full parameter set is not defined in the source.»*

**Что это значит для фичи:**
- Практически ничего нового — вопрос уже закрыт **DEC-005**: оси первой версии = power, frequency, speed; pulse width, hatch/line interval, passes, focus = константы профиля лазера, с возможностью добавлять оси позже.
- Полезное зерно: **focus и партия материала — не оси, но источники вариативности**. Их надо фиксировать как метаданные наблюдения, иначе анализ стабильности не сможет объяснить, почему «те же параметры» дали другой цвет.

**Встречный вопрос (связан с п.3 по импорту legacy-гравировок):** какие контекстные поля обязательны при записи любого наблюдения?
- A. Обязательны: профиль лазера, профиль материала (включая партию/ID листа), значение фокуса; опционально: дата, температура/примечание.
- B. Обязателен только профиль лазера; остальное — «неизвестно» по умолчанию (удобно для legacy-импорта, хуже для анализа стабильности).
- C. Своё.

Предлагаю **A** для стендовых плат и **B** для legacy-импорта — согласуется с разделением по провенансу.

### Answer to Q-012 · 2026-10-14

Что такое «AI» в Experiment Designer первой версии: алгоритм активного обучения, работающий офлайн, или внешняя LLM-модель?

Hybrid like B but I need to find out how to scan images, identify colors and mapt it to settings in lightburn file....

### Answer to Q-013 · 2026-10-14

Какие контекстные поля обязательны при записи наблюдения (ячейки платы или области гравировки), чтобы анализ стабильности мог объяснять расх

Honestly if I provide import/export Lightbirn files - it has all parameters, For photos of matrixes all parameters are described on the plate

### Answer to Q-014 · 2026-10-14

Подтвердите правило веса для legacy-наблюдений (импорт LightBurn + фото без стенда): должны ли они засчитываться в повторы для автопродвижен

This is not legacy and I can make photos of them on stand like others plus I'll operate always by this pair lightburn file and image

### AI updated the requirements · 2026-10-14

DEC-001, DEC-002, DEC-003, DEC-004, DEC-005, DEC-006, DEC-007, DEC-008, DEC-009, DEC-010, DEC-011, DEC-012, DEC-013, DEC-014, DEC-015 written into REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-009, REQ-010, REQ-011, REQ-013, REQ-015, REQ-016.

### AI updated the requirements · 2026-10-14

DEC-016 written into REQ-001, REQ-003, REQ-005, REQ-006, REQ-009, REQ-013, REQ-015, REQ-016.

### AI updated the requirements · 2026-10-14

DEC-017, DEC-018 written into REQ-001, REQ-003, REQ-004, REQ-005, REQ-010, REQ-015, REQ-016.

### Boris Tsekinovsky · 2026-10-14

Я хочу, чтобы ты использовал и очень внимательно и подробно прототип, который находится вот здесь - /Users/boris/github.com/titanium-color-engraving-intelligence-platform/.dde/prototypes/initial/export/initial-v10.zip

### AI · 2026-10-14

Принял: буду использовать **initial-v10 как конкретную основу для разбора экранов и сценариев**, вместе с требованиями и решениями.

Прочитал документацию архива и проверил ключевые участки исходников. Визуальную проверку интерфейса в браузере ещё не выполнял. Уже важно учесть:

- История ревью содержит дополнительные требования: удаление созданных записей с защитой связанных данных, тёмная тема, контраст и управление выбором версии профиля с клавиатуры.
- Чтение LightBurn, RAW/CV, модель и планировщик демонстрационные. Их поведение нельзя автоматически считать готовой производственной спецификацией.
- Есть расхождение: требования ограничивают **ожидаемую ошибку цвета**, а прототип проверяет **расстояние от целевого цвета до выбранного образца**. Эти показатели нужно развести.

Наиболее полезный следующий вопрос: **независимый повтор обязательно должен быть на новом физическом изделии, или отдельная гравировка на новом участке того же листа тоже считается повтором?** В прототипе повторы считаются по разным `pieceId`; это может исключать ваши реальные калибровочные эксперименты. Моя рекомендация — считать отдельные физические гравировки, сохраняя связь с листом; повторная фотография повтором гравировки не считается.

Решение, которое уже можно записать: использовать этот архив как источник для спецификации, отдельно отмечая демонстрационные значения, пробелы и противоречия.

### Answer to Q-015 · 2026-10-14

Which implementation stack should the single local web process use?

A. Python 3: FastAPI + SQLite, with OpenCV, rawpy and numpy/scikit-learn (RAW, chart correction, marker detection and the uncertainty model). The UI is served as static files from the same process.

### Answer to Q-016 · 2026-10-14

What counts as an independent repetition toward the 'repeated' and 'validated' stages?

A. Each separate physical engraving counts, whether on a new piece or a new area of the same sheet. The sheet link is kept for context. A re-photograph of the same engraving never counts.

### Answer to Q-017 · 2026-10-14

How should the importer use the pulse width and line interval that real .lbrn2 layers record?

A. Read pulse width and line interval from each layer when the file has them. Compare them with the linked profile's constants. If they differ, import the layer with a warning and mark it 'not comparable'. It never enters the model or the repetition counts. The stored parameter vector still takes its constants from the profile version. Focus, material batch and passes stay unknown, because the file doesn't record them.

### AI · 2026-10-14

Recorded DEC-020 (Python/FastAPI/SQLite stack), DEC-021 (independent repetition = separate physical engraving) and DEC-022 (layers with different constants are imported as not comparable) from the answers above. Marked DEC-012 superseded by DEC-015, aligned DEC-014 with DEC-017, fixed the stale REQ-014 reference in DEC-013 and filled the empty Consequences of DEC-019. Proposed DEC-023 (SemVer from 0.1.0) and DEC-024 (build a wheel and install it into a local virtual environment) because the repository defines no versioning or deploy rules; both wait for confirmation.
