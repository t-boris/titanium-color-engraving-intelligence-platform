/* Forms that say what they want and where they are wrong (feature ux-save-feedback-p0, REQ-003).
   - QUANTITIES: the units and permitted ranges that the server itself enforces, each with the place in the server that says so
     (``tests/test_save_feedback_ui.py`` checks every one of them against that place at its edges). Where the server has no rule, there is no
     range here: a limit is never made up (the speed of the scanner, for one, has none).
   - ``readNumber`` rejects what is not a number, not a whole number where one is needed, or outside the range. It never corrects it: not a
     «0» for an empty box, not the nearest permitted value. The rejected text stays in the box with the reason beside it.
   - ``create`` collects the fields of one form: it reads them, marks each bad one beside its input (aria-invalid, aria-describedby, focus on
     the first), and maps what the server says about fields (FastAPI's validation list, ``error.details``) onto the fields it names. What the
     server says about the form as a whole stays above the buttons as one message with what to do next, not in a toast that goes away. */
'use strict';
const Forms = (() => {
  const {h, field} = App;

  // ``min``/``max`` are the permitted ends; ``open`` marks an end that is not itself permitted. ``integer``: a whole number.
  // ``source`` names the rule of the server that this entry copies.
  const QUANTITIES = {
    power: {label: 'Мощность', unit: '%', min: 0, minOpen: true, max: 100, source: 'setup.check_in_range'},
    photoPower: {label: 'Мощность Min и Max', unit: '%', min: 0, max: 100, source: 'prediction_store.check_power_range'},
    pictureWidth: {label: 'Ширина картинки', unit: 'мм', min: 1, max: 1000, source: 'prediction_store.check_width'},
    globalPasses: {label: 'Проходы всей работы', unit: '', integer: true, min: 1, max: 100, source: 'plans.scan_settings'},
    passes: {label: 'Проходы', unit: '', integer: true, min: 1, source: 'setup.job_settings'},
    speed: {label: 'Скорость', unit: 'мм/с', min: 0, minOpen: true, source: 'setup._finite(positive); no limit of the scanner is known'},
    lineInterval: {label: 'Шаг строк', unit: 'мм', min: 0, minOpen: true, source: 'setup.job_settings'},
    pulseWidth: {label: 'Длительность импульса', unit: 'нс', min: 0, minOpen: true, source: 'setup.job_settings (and the laser\'s own steps)'},
    frequency: {label: 'Частота', unit: 'кГц', min: 0, minOpen: true, source: 'setup.check_in_range (the laser\'s own range narrows it)'},
    ratedPower: {label: 'Номинальная мощность', unit: 'Вт', min: 0, minOpen: true, source: 'devices.validate_passport'},
    wavelength: {label: 'Длина волны', unit: 'нм', min: 0, minOpen: true, source: 'devices.validate_passport'},
    repetitionRate: {label: 'Частота повторения', unit: 'кГц', min: 0, minOpen: true, source: 'devices.validate_passport (the lower end must lie below the upper)'},
    cutoff: {label: 'Частота среза', unit: 'кГц', min: 0, minOpen: true, source: 'devices.validate_passport'},
    m2: {label: 'M²', unit: '', min: 0, minOpen: true, source: 'devices.validate_passport'},
    beamDiameter: {label: 'Диаметр пучка', unit: 'мм', min: 0, minOpen: true, source: 'devices.validate_passport'},
    // second pass (the rules of the other screens); an entry without ``min``/``max`` is a number the server only requires to be finite
    labL: {label: 'L*', unit: '', min: 0, max: 100, source: 'tasks.clean_goals'},
    labAB: {label: 'a*, b*', unit: '', source: 'tasks.clean_goals (finite; the server states no range)'},
    lineWidth: {label: 'Ширина линии', unit: 'мм', min: 0, minOpen: true, source: 'tasks.clean_goals'},
    textHeight: {label: 'Высота текста', unit: 'мм', min: 0, minOpen: true, source: 'tasks.clean_goals'},
    analysisInterval: {label: 'Интервал пересчёта', unit: 'ч', min: 0, max: 8760, source: 'findings.set_interval'},
    proposalSize: {label: 'Число наборов', unit: '', integer: true, min: 1, max: 40, source: 'designer.propose'},
    seed: {label: 'Зерно', unit: '', integer: true, source: 'designer.propose (a whole number; no range)'},
    workWidth: {label: 'Ширина работы', unit: 'мм', min: 0, minOpen: true, source: 'conversion.raster'},
    photoColours: {label: 'Число цветов', unit: '', integer: true, min: 2, max: 29, source: 'vector_job._split_settings (up to 28 with the markers: the caller narrows it)'},
    maxTime: {label: 'Наибольшее время гравировки', unit: 'с/см²', min: 0, minOpen: true, source: 'colormap.time_limit'},
    vectorTolerance: {label: 'Точность контура', unit: 'мм', min: 0, source: 'vector_job._split_settings and vectorize._number'},
    greyThreshold: {label: 'Порог серого', unit: '', min: 0, max: 255, source: 'vectorize._binarise'},
    deltaE: {label: 'Допуск ΔE', unit: 'ΔE', min: 0, source: 'conversion._threshold'},
    toneBrightness: {label: 'Яркость картинки', unit: '%', min: -100, max: 100, source: 'photo_state.TONE_LIMITS'},
    toneContrast: {label: 'Контраст картинки', unit: '%', min: -100, max: 100, source: 'photo_state.TONE_LIMITS'},
    toneGamma: {label: 'Гамма картинки', unit: '', min: 0.2, max: 5, source: 'photo_state.TONE_LIMITS'},
    sharpness: {label: 'Чёткость картинки', unit: '', min: 0, max: 100, source: 'photo_state.change'},
    matrixCount: {label: 'Столбцов или строк', unit: '', integer: true, min: 1, max: 900, source: 'matrix.apply_edit (a matrix has 1 to 900 cells: the two together)'},
    matrixShift: {label: 'Сдвиг первой ячейки', unit: 'ячеек', integer: true, source: 'matrix.apply_edit (a whole number; the server would cut a fraction off, the form refuses it)'},
    matrixSetting: {label: 'Значение настройки', unit: '', source: 'matrix.apply_edit (a number; the ranges are judged when the layers are checked)'},
    matrixPitch: {label: 'Шаг ячеек', unit: 'мм', source: 'matrix.apply_edit (a number; the server states no range)'},
    // the fields of an inscription (lettering.NUMBERS): the unit is in the name of the box, the ends are the server's
    letterHeight: {label: 'Высота букв', unit: 'мм', min: 0.3, max: 500, source: 'lettering.NUMBERS'},
    letterWidth: {label: 'Ширина букв', unit: '%', min: 10, max: 400, source: 'lettering.NUMBERS'},
    letterSpacing: {label: 'Интервал между буквами', unit: 'мм', min: -50, max: 200, source: 'lettering.NUMBERS'},
    lineSpacing: {label: 'Между строками', unit: '%', min: 50, max: 400, source: 'lettering.NUMBERS'},
    letterRotation: {label: 'Поворот надписи', unit: '°', min: -3600, max: 3600, source: 'lettering.NUMBERS'},
    letterBend: {label: 'Изгиб', unit: '%', min: -100, max: 100, source: 'lettering.NUMBERS'},
    circleRadius: {label: 'Радиус круга', unit: 'мм', min: 0.5, max: 5000, source: 'lettering.NUMBERS'},
    circleStart: {label: 'Где на круге', unit: '°', min: -3600, max: 3600, source: 'lettering.NUMBERS'},
    pathOffset: {label: 'Место на пути', unit: '%', min: 0, max: 100, source: 'lettering.NUMBERS'},
    letterGap: {label: 'Зазор вокруг букв', unit: 'мм', min: 0, max: 20, source: 'lettering.NUMBERS'},
    backingPadding: {label: 'Поле подложки', unit: 'мм', min: 0, max: 200, source: 'lettering.NUMBERS'},
    backingCorner: {label: 'Скругление углов подложки', unit: 'мм', min: 0, max: 200, source: 'lettering.NUMBERS'},
    letterX: {label: 'Положение x', unit: 'мм', min: -100000, max: 100000, source: 'lettering.NUMBERS'},
    letterY: {label: 'Положение y', unit: 'мм', min: -100000, max: 100000, source: 'lettering.NUMBERS'},
    pathPoint: {label: 'Точка пути', unit: 'мм', min: -100000, max: 100000, source: 'lettering._points'},
    dotWidth: {label: 'Ширина точки лазера', unit: 'мм', min: 0.001, max: 0.2, source: 'photo_state.dot_width_in (kept to a thousandth of a mm)'},
    schemeRotation: {label: 'Поворот схемы', unit: '°', min: 0, max: 360, source: 'ingest._overlay_override'},
    schemeScale: {label: 'Масштаб схемы', unit: '%', min: 10, max: 800, source: 'ingest._overlay_override (a factor of 0.1 to 8)'},
    focus: {label: 'Фокус', unit: '', source: 'ingest.clean_context (finite; the server states no range and no unit)'},
    thickness: {label: 'Толщина', unit: 'мм', min: 0, minOpen: true, source: 'setup.save_material'},
    cellSize: {label: 'Размер ячейки', unit: 'мм', min: 0, minOpen: true, source: 'plans.build_grid'},
    gap: {label: 'Промежуток', unit: 'мм', min: 0, source: 'plans.build_grid'},
    lanPort: {label: 'Порт', unit: '', integer: true, min: 1024, max: 65535, source: 'lan.save_settings'},
    focal: {label: 'Фокусное расстояние', unit: 'мм', min: 20, max: 1500, source: 'lenses.FOCAL_RANGE_MM'},
    lensField: {label: 'Поле линзы', unit: 'мм', min: 1, max: 500, source: 'lenses.FIELD_RANGE_MM'},
    expansion: {label: 'Расширение пучка', unit: '×', min: 0.2, max: 20, source: 'lenses.EXPANSION_RANGE'},
    spot: {label: 'Диаметр пятна', unit: 'мкм', min: 1, max: 2000, source: 'lenses.SPOT_RANGE_UM'},
    // third pass (the rules of the sliders and the boxes of the vector work, the rules of evaluation, the lookup of a measured result)
    density: {label: 'Плотность областей', unit: '', integer: true, min: 30, max: 250, source: 'vector_job._split_settings (DENSITY)'},
    smoothing: {label: 'Гладкость линий', unit: 'мм', min: 0, max: 2, source: 'vector_job.smooth (SMOOTHING_MAX_MM; the work says its own end)'},
    similarity: {label: 'Похожесть', unit: 'ΔE', min: 0, source: 'vector_job._similarity (a non-negative delta E; no upper end)'},
    splitColours: {label: 'Число цветов', unit: '', integer: true, min: 2, max: 8, source: 'vector_job._split_region (segment.SPLIT_AGAIN_MAX)'},
    repeatThreshold: {label: 'Сколько гравировок повторить', unit: '', integer: true, min: 1, source: 'setup.save_rules'},
    deltaTolerance: {label: 'Допуск цветового отклонения', unit: 'ΔE', min: 0, source: 'setup.save_rules'},
    varianceThreshold: {label: 'Допустимая дисперсия цвета', unit: '', min: 0, source: 'setup.save_rules'},
    // the lookup of a measured result compares exact settings: its models (api.routes_devices.ResultLookupIn) take any number, passes a whole one
    // the marker layer is saved with the rule of plans.save_marker_layer_settings: above 0 (the laser's own range is judged when a plate is made)
    markerPower: {label: 'Мощность', unit: '%', min: 0, minOpen: true, source: 'plans.save_marker_layer_settings'},
    markerFrequency: {label: 'Частота', unit: 'кГц', min: 0, minOpen: true, source: 'plans.save_marker_layer_settings'},
    markerSpeed: {label: 'Скорость', unit: 'мм/с', min: 0, minOpen: true, source: 'plans.save_marker_layer_settings'},
    markerPulse: {label: 'Q-Pulse', unit: 'нс', min: 0, minOpen: true, source: 'plans.save_marker_layer_settings'},
    markerInterval: {label: 'Интервал линий', unit: 'мм', min: 0, minOpen: true, source: 'plans.save_marker_layer_settings'},
    markerPasses: {label: 'Проходы', unit: '', integer: true, min: 1, source: 'plans.save_marker_layer_settings'},
    // the wanted colour of the colour map's search and its tolerance (api.routes_work.search_colors, colormap.delta_tolerance)
    targetL: {label: 'L', unit: '', source: 'api.routes_work.search_colors (any number)'},
    targetAB: {label: 'a, b', unit: '', source: 'api.routes_work.search_colors (any number)'},
    searchTolerance: {label: 'Допуск ΔE', unit: 'ΔE', min: 0, source: 'colormap.delta_tolerance'},
    // the colour for the prediction of settings (model.predict_for_lab -> color.valid_lab)
    predictL: {label: 'L', unit: '', min: 0, max: 100, source: 'color.valid_lab'},
    predictAB: {label: 'a, b', unit: '', min: -128, max: 127, source: 'color.valid_lab'},
    bandCount: {label: 'Число полос', unit: '', integer: true, min: 1, max: 29, source: 'conversion._check_bands (up to MAX_BANDS: the screen asks the server for it)'},
    lookupPower: {label: 'Мощность', unit: '%', source: 'api.routes_devices.ResultLookupIn (any number: a lookup matches exact settings)'},
    lookupFrequency: {label: 'Частота', unit: 'кГц', source: 'api.routes_devices.ResultLookupIn (any number)'},
    lookupSpeed: {label: 'Скорость', unit: 'мм/с', source: 'api.routes_devices.ResultLookupIn (any number)'},
    lookupPulse: {label: 'Импульс', unit: 'нс', source: 'api.routes_devices.ResultLookupIn (any number)'},
    lookupInterval: {label: 'Шаг линий', unit: 'мм', source: 'api.routes_devices.ResultLookupIn (any number)'},
    lookupPasses: {label: 'Проходы', unit: '', integer: true, source: 'api.routes_devices.ResultLookupIn (a whole number)'},
    // the experimental plate (capability_plates): the settings of a test, the size of a plate and the grids of its types. The laser's own range of
    // frequency and pulse width narrows ``frequency`` and ``pulseWidth`` (the dialog reads it from the laser's passport).
    platePower: {label: 'Мощность', unit: '%', min: 0, minOpen: true, max: 100, source: 'capability_plates._passport_defaults'},
    plateSpeed: {label: 'Скорость', unit: 'мм/с', min: 0, minOpen: true, max: 10000, source: 'capability_plates._passport_defaults'},
    plateInterval: {label: 'Интервал линий', unit: 'мм', min: 0, minOpen: true, max: 1, source: 'capability_plates._passport_defaults'},
    platePasses: {label: 'Проходы', unit: '', integer: true, min: 1, max: 20, source: 'capability_plates._passport_defaults'},
    plateSize: {label: 'Предельный размер платы', unit: 'мм', min: 1, max: 300, source: 'capability_plates.preview (PLATE_MAX_MM)'},
    matrixPoints: {label: 'Точек по оси', unit: '', integer: true, min: 2, max: 7, source: 'capability_plates._matrix_settings'},
    wobbleStep: {label: 'Шаг wobble', unit: 'мм', min: 0.001, max: 1, source: 'capability_plates._matrix_settings'},
    plateAxisPower: {label: 'Мощность по оси', unit: '%', min: 1, max: 100, source: 'capability_plates._matrix_settings (domain)'},
    plateAxisSpeed: {label: 'Скорость по оси', unit: 'мм/с', min: 1, max: 10000, source: 'capability_plates._matrix_settings (domain)'},
    plateAxisInterval: {label: 'Интервал линий по оси', unit: 'мм', min: 0.001, max: 1, source: 'capability_plates._matrix_settings (domain)'},
    plateAxisPasses: {label: 'Проходы по оси', unit: '', integer: true, min: 1, max: 20, source: 'capability_plates._matrix_settings (domain)'},
    plateAxisWobble: {label: 'Диаметр wobble по оси', unit: 'мм', min: 0, max: 1, source: 'capability_plates._matrix_settings (domain)'},
    greyPower: {label: 'Min и Max мощность', unit: '%', min: 0, max: 100, source: 'capability_plates._grey_scales (and Min below Max)'},
    rampWidth: {label: 'Ширина полоски', unit: 'мм', min: 16, source: 'capability_plates._grey_axis (a step of at least 1 mm: 16 steps)'},
    fillWidth: {label: 'Ширина полоски заливки', unit: 'мм', min: 3, max: 300, source: 'capability_plates._fill_widths'},
    copySize: {label: 'Размер копии', unit: 'мм', min: 8, max: 40, source: 'capability_plates.VARIATION_COPY_MM'},
    copyMinPower: {label: 'Min мощность копий', unit: '%', min: 0, source: 'capability_plates._variant (and below the plate\'s power)'}};

  // The reach of a control that only changes how a picture is looked at; nothing of it is sent to the server and no server rule stands behind it.
  // The range is the control's own (the ends of its slider), told as it is: it is not a rule of the product.
  const VIEWS = {
    viewRotation: {label: 'Поворот фотографии для просмотра', unit: '°', min: 0, max: 360},
    viewZoom: {label: 'Масштаб просмотра фотографии', unit: '%', min: 25, max: 800},
    similarityReach: {label: 'Похожесть, ползунком', unit: 'ΔE', min: 0.5, max: 30},
    lightnessBand: {label: 'Светлота L* (показ на карте)', unit: '', min: 0, max: 100},
    objectShift: {label: 'Светлее или темнее', unit: '', min: -1, max: 1},
    // a corner of the plate on the photograph is a place inside it, as a share of its width and height: the picture's own edges, not a rule of the server
    cornerShare: {label: 'Положение угла на снимке', unit: '%', min: 0, max: 100}};

  const show = (n) => String(+n).replace('.', ',');
  /** The permitted values in words: «больше 0 и не больше 100», «от 20 до 1500», «целое, не меньше 1». */
  function constraint(q) {
    const lo = q.min, hi = q.max;
    let text;
    if (lo != null && hi != null && q.maxOpen) text = q.minOpen ? `больше ${show(lo)} и меньше ${show(hi)}` : `от ${show(lo)}, меньше ${show(hi)}`;
    else if (lo != null && hi != null && !q.minOpen) text = `от ${show(lo)} до ${show(hi)}`;
    else if (lo != null && hi != null) text = `больше ${show(lo)} и не больше ${show(hi)}`;
    else if (lo != null) text = q.minOpen ? `больше ${show(lo)}` : `не меньше ${show(lo)}`;
    else if (hi != null) text = q.maxOpen ? `меньше ${show(hi)}` : `не больше ${show(hi)}`;
    else text = '';
    return [q.integer ? 'целое число' : null, text].filter(Boolean).join(', ');
  }
  const inside = (q, v) => (q.min == null || (q.minOpen ? v > q.min : v >= q.min)) && (q.max == null || (q.maxOpen ? v < q.max : v <= q.max));
  const NUMBER = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$/;

  /** Read ``text`` as a quantity ``q`` (an entry of QUANTITIES or the same shape; ``opts.min``/``opts.max`` narrow it to what a device allows).
      {ok: true, value} (``null`` for an empty optional box) or {ok: false, message}. Nothing is adjusted. */
  function parse(text, q = {}, opts = {}) {
    const rule = {...q, ...(opts.min !== undefined ? {min: opts.min, minOpen: !!opts.minOpen} : {}), ...(opts.max !== undefined ? {max: opts.max, maxOpen: !!opts.maxOpen} : {})};
    const raw = String(text ?? '').trim();
    if (raw === '') return opts.required ? {ok: false, message: 'Заполните это поле'} : {ok: true, value: null};
    if (!NUMBER.test(raw)) return {ok: false, message: `Введите число${rule.unit ? `, ${rule.unit}` : ''}. Введено: «${raw}»`};
    const value = Number(raw.replace(',', '.'));
    if (!Number.isFinite(value)) return {ok: false, message: `Введите число${rule.unit ? `, ${rule.unit}` : ''}. Введено: «${raw}»`};
    if (rule.integer && !Number.isInteger(value)) return {ok: false, message: `Нужно целое число. Введено: ${show(value)}`};
    if (!inside(rule, value)) {
      const words = constraint(rule);
      return {ok: false, message: `Допустимо: ${words}${rule.unit ? ` ${rule.unit}` : ''}. Введено: ${show(value)}`};
    }
    return {ok: true, value};
  }
  /** The same for a number box: a browser gives an empty string for text that is not a number (``validity.badInput``), which is not «empty». */
  function readNumber(input, q, opts = {}) {
    if (input.validity && input.validity.badInput) return {ok: false, message: `Введите число${q && q.unit ? `, ${q.unit}` : ''}`};
    return parse(input.value, q, opts);
  }
  /** A number box for ``q``: its closed ends are the box's own limits (the arrows stay inside them; typing still can leave and is then refused). */
  function numberInput(q, attrs = {}) {
    const bounds = {};
    if (q && q.min != null && !q.minOpen) bounds.min = String(q.min);
    if (q && q.max != null && !q.maxOpen) bounds.max = String(q.max);
    return h('input', {type: 'number', step: q && q.integer ? '1' : 'any', inputmode: q && q.integer ? 'numeric' : 'decimal', ...bounds, ...attrs});
  }

  const tooLong = (text, o) => (o.maxLength && text.length > o.maxLength ? {ok: false, message: `Не больше ${o.maxLength} символов. Введено: ${text.length}`}
    : o.minLength && text.trim().length < o.minLength ? {ok: false, message: `Не меньше ${o.minLength} символов. Введено: ${text.trim().length}`} : null);
  const defaultRead = (input, q, o) => {
    if (o.quantity || (input.getAttribute && input.getAttribute('type') === 'number')) return () => readNumber(input, q, o);
    if (input.localName === 'input' && input.getAttribute('type') === 'checkbox') return () => ({ok: true, value: !!input.checked});
    // ``raw``: the text is sent exactly as typed (the server decides what a name or a note may contain)
    if (o.raw) {
      return () => {
        const text = String(input.value ?? '');
        if (o.required && text.trim() === '') return {ok: false, message: 'Заполните это поле'};
        return tooLong(text, o) || {ok: true, value: text};
      };
    }
    return () => {
      const v = String(input.value ?? '').trim();
      if (v === '' && o.required) return {ok: false, message: 'Заполните это поле'};
      return tooLong(v, o) || {ok: true, value: v === '' ? (o.empty === undefined ? null : o.empty) : v};
    };
  };

  /** A form controller. ``add`` makes a field (App.field with the units, the permitted values and «обязательно» in its words) and registers it;
      ``collect`` reads all of them (null, with every bad field marked and the first focused, when any is bad); ``fail`` puts a server error
      where it belongs; ``error`` is the form-wide message (place it above the buttons). */
  function create() {
    const entries = [];
    const error = h('p', {class: 'alert bad f-form-error', role: 'alert', hidden: true});
    const say = (text) => { error.textContent = text; error.hidden = !text; };
    function add(name, label, input, o = {}) {
      const q = typeof o.quantity === 'string' ? QUANTITIES[o.quantity] : o.quantity || null;
      if (o.quantity && !q) throw new Error(`unknown quantity ${o.quantity}`);
      const rule = q ? {...q, ...(o.min !== undefined ? {min: o.min, minOpen: !!o.minOpen} : {}), ...(o.max !== undefined ? {max: o.max, maxOpen: !!o.maxOpen} : {})} : null;
      const words = rule ? constraint(rule) : o.minLength && o.maxLength ? `от ${o.minLength} до ${o.maxLength} символов` : o.maxLength ? `не больше ${o.maxLength} символов`
        : o.minLength ? `не меньше ${o.minLength} символов` : '';
      const unit = o.unit ?? (q && q.unit) ?? '';
      const el = field(label, input, o.help, {required: !!o.required, unit, unitless: !!q && !unit, constraint: o.constraint ?? (words ? `допустимо: ${words}` : '')});
      const entry = {name, label, el, input, read: o.read || defaultRead(input, q, o)};
      entries.push(entry);
      const edited = () => { el.clearError(); say(''); };
      input.addEventListener('input', edited);
      input.addEventListener('change', edited);
      return el;
    }
    const focusOn = (entry) => { const c = entry.el.firstControl(); if (c && c.focus) c.focus(); };
    function collect() {
      say('');
      const values = {};
      const bad = [];
      for (const entry of entries) {
        const r = entry.read();
        if (r.ok) { values[entry.name] = r.value; entry.el.clearError(); } else { entry.el.setError(r.message); bad.push(entry); }
      }
      if (!bad.length) return values;
      focusOn(bad[0]);
      say(`Не отправлено: ${bad.length === 1 ? 'исправьте поле' : 'исправьте поля'} ${bad.map((b) => `«${b.label}»`).join(', ')}. Всё, что вы ввели, осталось в форме.`);
      return null;
    }
    /** An error of the server: the fields it names get its words; the rest, and any error that names no field, is said for the whole form. */
    function fail(e) {
      const details = (e && e.details) || [];
      const rest = [];
      const marked = [];
      for (const d of details) {
        const entry = entries.find((x) => x.name === d.field);
        if (entry) { entry.el.setError(d.message); marked.push(entry); } else rest.push(d.message);
      }
      if (marked.length) {
        focusOn(marked[0]);
        say(`Сервер не принял ${marked.length === 1 ? 'поле' : 'поля'} ${marked.map((m) => `«${m.label}»`).join(', ')}: исправьте ${marked.length === 1 ? 'его' : 'их'} и отправьте снова.`
          + (rest.length ? ` Ещё: ${rest.join('; ')}.` : ''));
        return;
      }
      const kind = e && e.kind === 'invalid' ? 'Сервер не принял данные' : 'Не получилось отправить';
      say(`${kind}: ${(e && e.message) || e}. Всё, что вы ввели, осталось в форме — исправьте и отправьте снова.`);
    }
    function clear() { say(''); for (const entry of entries) entry.el.clearError(); }
    return {add, collect, fail, clear, error, entries};
  }

  /** A number box that has no field around it because it is the partner of a slider in a row of controls: what is typed is checked when the box
      is left, a wrong value is kept in the box and the reason is drawn right after it (``aria-invalid``, ``aria-describedby``); only a right value
      reaches ``apply``. The caller puts the returned note into the row. ``o.wrong(text)`` is told of a wrong value as well: a control whose changes go
      through a document tracker (save-state.js) passes it on, so that the tracker, and not only the note, knows the screen holds what is not stored. */
  let noteSeq = 0;
  function watch(input, q, apply, o = {}) {
    const quantity = typeof q === 'string' ? (QUANTITIES[q] || VIEWS[q]) : q;
    const note = h('span', {class: 'small f-error', id: `f-note-${++noteSeq}`, 'aria-live': 'polite'});
    input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), note.getAttribute('id')].filter(Boolean).join(' '));
    input.addEventListener('change', () => {
      const r = parse(String(input.value ?? ''), quantity, o);
      if (!r.ok) { input.setAttribute('aria-invalid', 'true'); note.textContent = r.message; if (o.wrong) o.wrong(String(input.value ?? '')); return; }
      input.removeAttribute('aria-invalid');
      note.textContent = '';
      apply(r.value);
    });
    return note;
  }

  /** What a box takes, in words for a screen reader: «единица: мм · допустимо: от 0 до 2» (a quantity without a unit says «без единицы»). ``q`` is a
      key of QUANTITIES or VIEWS, or a rule of the same shape (a QUANTITIES entry narrowed to what the work allows). */
  function rulesText(q) {
    const range = constraint(q);
    return [q.unit ? `единица: ${q.unit}` : 'без единицы', range ? `допустимо: ${range}` : null].filter(Boolean).join(' · ');
  }
  /** A control that stands in a row, not in a field (a slider, a number box beside it): its unit and permitted values are read after its name.
      The caller puts the returned note (invisible, for the screen reader) next to the control. ``o.extra`` adds words of the caller's own. */
  function describe(input, q, o = {}) {
    const rule = typeof q === 'string' ? (QUANTITIES[q] || VIEWS[q]) : q;
    if (!rule) throw new Error(`unknown quantity ${q}`);
    const id = `f-note-${++noteSeq}`;
    const note = h('span', {class: 'sr-only', id}, rulesText(rule) + (o.extra ? ` · ${o.extra}` : ''));
    input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), id].filter(Boolean).join(' '));
    return note;
  }

  /** A place beside a control that acts at once (a slider, a choice, a button of a row) for what the server refused to do with it. It has the
      two things of a form that the screens use, ``fail`` and ``clear``, and ``error`` (the node to place): ``run(op, place)`` takes either. ``o.what``
      names the action («Перекраска»), ``o.kept`` says what stayed as it was. */
  function notice(o = {}) {
    const error = h('p', {class: 'alert bad f-form-error', role: 'alert', hidden: true, id: `f-note-${++noteSeq}`});
    let control = null;                                                    // the box this notice is about (``attach``): read with the notice and marked while it speaks
    const say = (text) => {
      error.textContent = text; error.hidden = !text;
      if (control) { if (text) control.setAttribute('aria-invalid', 'true'); else control.removeAttribute('aria-invalid'); }
    };
    return {error, clear: () => say(''), say,
      attach(input) {
        control = input;
        input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), error.getAttribute('id')].filter(Boolean).join(' '));
        return input;
      },
      fail(e) { say(`${o.what ? `${o.what} не выполнена` : 'Не получилось'}: ${(e && e.message) || e}. ${o.kept || 'Всё осталось как было.'}`); }};
  }

  return {QUANTITIES, VIEWS, constraint, rulesText, parse, readNumber, numberInput, watch, describe, notice, create};
})();
