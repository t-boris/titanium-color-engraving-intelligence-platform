/* Создание экспериментальной платы: лазер и материал задаются здесь, оборудование хранится в контексте опыта. */
'use strict';
const PlateDialog = (() => {
  const {h, btn, field, get, post, toast, modal, go} = App;
  const UNCHECKED = 'поле линзы неизвестно — размещение не проверено';

  /** Проверка размещения по рабочему полю лазера и линзы (REQ-018): неизвестное поле — не «помещается», а «не проверено». */
  function placementText(summary) {
    const w = summary && summary.work_field;
    if (!w) return '';
    return w.checked ? `помещается в рабочее поле ${w.field_mm.width} × ${w.field_mm.height} мм` : UNCHECKED;
  }
  const placement = (summary) => {
    const text = placementText(summary);
    return text ? h('span', {class: summary.work_field.checked ? 'muted' : 'pill warn'}, ` · ${text}`) : null;
  };

  const DEFAULTS = {power: 20, frequency: 48, speed: 900, pulse_width: 200, line_interval: 0.025, passes: 1, global_passes: 1};
  const MATRIX_AXES = {
    power: {name: 'Мощность, %', min: 5, max: 100}, speed: {name: 'Скорость, мм/с', min: 500, max: 10000},
    frequency: {name: 'Частота, кГц', min: 24, max: 96}, pulse_width: {name: 'Q-Pulse, нс', min: 2, max: 500},
    line_interval: {name: 'Интервал линий, мм', min: 0.01, max: 0.2}, passes: {name: 'Проходы', min: 1, max: 5},
    wobble_size: {name: 'Диаметр wobble, мм (0 = выкл.)', min: 0, max: 0.08},
  };
  // REQ-059: шкалы серого — две оси из этих параметров и ширины полоски; по умолчанию строки — шаг линий (2000/1500/1200/1000 dpi), столбцы — скорость
  const GREY_AXES = ['line_interval', 'speed', 'frequency', 'pulse_width', 'passes', 'width'];
  const greyAxisName = (key) => key === 'width' ? 'Ширина полоски, мм' : MATRIX_AXES[key].name;
  const GREY_DEFAULTS = {rows: 'line_interval', rowValues: '0.0127, 0.0169, 0.0212, 0.0254', columns: 'speed', columnValues: '100, 150, 250',
    min: 1, max: 40, speed: 150, frequency: 60, interval: 0.0169};
  // Размер заливки: полоски этих ширин для каждого рецепта; рецепт — основные параметры опыта с одним изменённым параметром
  const FILL_AXES = ['power', 'speed', 'frequency', 'pulse_width', 'line_interval', 'passes'];
  const FILL_WIDTHS = '5, 20, 50, 100';
  const PHOTO_KINDS = [['jarvis', 'Jarvis'], ['atkinson', 'Atkinson'], ['stucki', 'Stucki'], ['grayscale', 'Градации серого']];
  /** The bytes of a file as base64 (the plate's picture travels inside the JSON of the plate). */
  async function base64Of(file) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let text = '';
    for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(text);
  }

  /** ``materials`` is no longer read: the stock record is chosen in the selector, which asks the server for what it shows (ux-growing-collections-p0,
      REQ-001); a caller may pass an array, null or nothing. */
  async function open(devices, materials, reload, preset = {}) {
    const typeRows = await get('/plate-types');
    const available = (devices || []).filter((d) => d.lens);
    // The numbers of the dialog are read strictly, with the rules the server states (ux-save-feedback-p0, REQ-003): a wrong one is marked beside its
    // box with the reason and stays as typed; what the server refuses is said in the dialog, never in a toast that goes away.
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const dynamic = [];                              // [{el, words}]: boxes whose permitted values follow the laser or the chosen axis
    const currentLaser = () => available.find((d) => String(d.id) === device.value) || available[0];
    const frequencyRule = () => {
      const r = currentLaser()?.passport?.repetition_rate_khz;
      return r ? {...Q.frequency, min: +r.min, minOpen: false, max: +r.max} : Q.frequency;
    };
    const pulseRule = () => {
      const steps = (currentLaser()?.passport?.pulse_steps || []).map((x) => +x.pulse_width_ns).filter(Number.isFinite);
      return steps.length ? {...Q.pulseWidth, min: Math.min(...steps), minOpen: false, max: Math.max(...steps)} : Q.pulseWidth;
    };
    // the quantity a setting has on a matrix axis, on a grey-ramp axis and in a recipe or a patch (the three kinds of grid have slightly different domains)
    const AXIS_RULES = {
      matrix: {power: 'plateAxisPower', speed: 'plateAxisSpeed', line_interval: 'plateAxisInterval', passes: 'plateAxisPasses', wobble_size: 'plateAxisWobble'},
      grey: {speed: 'plateSpeed', line_interval: 'plateAxisInterval', passes: 'platePasses', width: 'rampWidth'},
      recipe: {power: 'platePower', speed: 'plateSpeed', line_interval: 'plateInterval', passes: 'platePasses'},
    };
    const axisRule = (kind, axis) => (axis === 'frequency' ? frequencyRule() : axis === 'pulse_width' ? pulseRule() : Q[AXIS_RULES[kind][axis]]);
    const refreshRules = () => { for (const {el, words} of dynamic) el.setHelp(words()); };
    // a box of a card that is hidden, or one the chosen kind does not use, is not asked (``o.card``, ``o.when``: functions, read when the dialog is sent)
    const skipped = (o) => (o.card && o.card().style.display === 'none') || (o.when && !o.when());
    const none = {ok: true, value: null};
    /** A number box whose permitted values are computed (the laser's range, the chosen axis); ``o.after(result)`` adds a rule between boxes. */
    const addNumber = (name, label, input, rule, o = {}) => {
      const el = form.add(name, label, input, {required: true, help: 'допустимые значения — по выбранному лазеру и параметру',
        read: () => (skipped(o) ? none : (o.after || ((r) => r))(Forms.readNumber(input, rule(), {required: true})))});
      dynamic.push({el, words: () => Forms.rulesText(rule())});
      return el;
    };
    /** A number box whose rule is fixed (a quantity of forms.js). */
    const addFixed = (name, label, input, quantity, o = {}) => form.add(name, label, input, {quantity, required: true,
      read: () => (skipped(o) ? none : (o.after || ((r) => r))(Forms.readNumber(input, Q[quantity], {required: true})))});
    /** Numbers typed with commas («5, 20, 50»): each is read by ``rule``; ``o.max`` is how many the plate takes, ``o.distinct`` that no two are alike. */
    const addList = (name, label, input, rule, o = {}) => {
      const el = form.add(name, label, input, {required: !o.optional, help: 'числа через запятую', read: () => {
        if (skipped(o)) return none;
        const parts = input.value.split(/[,;\s]+/).filter(Boolean);
        if (!parts.length) return o.optional ? none : {ok: false, message: 'Заполните это поле'};
        const values = [];
        for (const [i, part] of parts.entries()) {
          const r = Forms.parse(part, rule(), {required: true});
          if (!r.ok) return {ok: false, message: `Значение ${i + 1}: ${r.message}`};
          values.push(r.value);
        }
        if (o.max && values.length > o.max) return {ok: false, message: `Не больше ${o.max} значений. Введено: ${values.length}`};
        if (o.distinct && new Set(values).size !== values.length) return {ok: false, message: 'Значения должны быть разными'};
        return (o.after || ((r) => r))({ok: true, value: values});
      }});
      dynamic.push({el, words: () => `${Forms.rulesText(rule())} · числа через запятую${o.max ? `, не больше ${o.max}` : ''}${o.distinct ? ', все разные' : ''}`});
      return el;
    };
    const type = h('select', {'aria-label': 'Тип экспериментальной платы'}, h('option', {value: '', selected: true}, 'выберите тип платы'));
    const device = h('select', {'aria-label': 'Лазер'}, available.map((d) => h('option', {value: d.id}, `${d.name}${d.serial ? ` · ${d.serial}` : ''}`)));
    // nothing is chosen until the caller or the workshop's last choice names a record (below); one concrete batch or sheet, never a grade
    const material = MaterialPicker.create({allowEmpty: true, clearLabel: 'Снять выбор', empty: 'выберите конкретную заготовку', title: 'Выбор заготовки для платы', name: 'Заготовка'});
    const desc = h('div', {class: 'stack muted small'});
    const hardware = h('p', {class: 'muted small'});
    const maxWidth = Forms.numberInput(Q.plateSize, {value: '100'});
    const maxHeight = Forms.numberInput(Q.plateSize, {value: '100'});
    const patch = {
      count: h('select', {'aria-label': 'Число квадратов'}, [1, 2, 4].map((n) => h('option', {value: n}, String(n)))),
      size: h('select', {'aria-label': 'Размер квадрата'}, [3, 5].map((n) => h('option', {value: n}, `${n} × ${n} мм`))),
      registration: h('select', {'aria-label': 'Совмещение фото'}, [h('option', {value: 'none'}, 'Без меток · минимум площади'),
        h('option', {value: 'full'}, 'QR + 4 метки · проще совместить фото')]),
      axis: h('select', {'aria-label': 'Менять параметр'}, ['power', 'speed', 'frequency', 'pulse_width', 'line_interval', 'passes']
        .map((key) => h('option', {value: key}, MATRIX_AXES[key].name))),
      values: h('input', {placeholder: 'Например: 5, 20, 50, 100'}),
    };
    const patchSweep = h('div', {class: 'grid g2'}, field('Менять параметр', patch.axis),
      addList('patch_values', 'Значения по квадратам, слева направо', patch.values, () => axisRule('recipe', patch.axis.value), {card: () => smallCard, when: () => +patch.count.value > 1,
        after: (r) => (r.ok && r.value.length !== +patch.count.value ? {ok: false, message: `Для ${patch.count.value} квадратов нужно ровно ${patch.count.value} чисел. Введено: ${r.value.length}`} : r)}));
    const previewText = h('div', {class: 'muted small', 'aria-live': 'polite'},
      'Размер покажем до создания файла; каждый файл чистит только свою область.');
    const smallCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Один–четыре квадрата. Если они не помещаются, получатся отдельные LightBurn-файлы. Без меток расход минимален, но совмещение фото может потребовать ручной правки.'),
      h('div', {class: 'grid g3'}, field('Число квадратов', patch.count), field('Размер квадрата', patch.size),
        field('Совмещение фото', patch.registration)),
      patchSweep, previewText);
    const patchDefaults = () => {
      const n = +patch.count.value;
      const laser = available.find((d) => String(d.id) === device.value) || available[0];
      const steps = (laser?.passport?.pulse_steps || []).map((s) => +s.pulse_width_ns).filter(Number.isFinite);
      const rate = laser?.passport?.repetition_rate_khz || {min: 24, max: 96};
      const defaults = {
        power: n === 2 ? [10, 50] : [5, 20, 50, 100],
        speed: n === 2 ? [500, 5000] : [500, 1500, 5000, 10000],
        frequency: n === 2 ? [rate.min, rate.max] : [rate.min, +settings.frequency.value, (rate.min + rate.max) / 2, rate.max],
        pulse_width: n === 2 ? [steps[0], steps[steps.length - 1]] :
          [steps[0], steps[Math.floor((steps.length - 1) / 3)], steps[Math.floor(2 * (steps.length - 1) / 3)], steps[steps.length - 1]],
        line_interval: n === 2 ? [0.01, 0.1] : [0.01, 0.025, 0.05, 0.1],
        passes: n === 2 ? [1, 3] : [1, 2, 3, 4],
      };
      patch.values.value = (defaults[patch.axis.value] || []).slice(0, n).filter(Number.isFinite).join(', ');
      patchSweep.style.display = n === 1 ? 'none' : '';
      previewText.textContent = 'Размер покажем до создания файла; каждый файл чистит только свою область.';
    };
    const matrix = {
      xAxis: h('select', {'aria-label': 'Ось X матрицы'}), yAxis: h('select', {'aria-label': 'Ось Y матрицы'}),
      xMin: h('input', {type: 'number', step: 'any', value: 5}), xMax: h('input', {type: 'number', step: 'any', value: 100}),
      yMin: h('input', {type: 'number', step: 'any', value: 500}), yMax: h('input', {type: 'number', step: 'any', value: 10000}),
      xCount: Forms.numberInput(Q.matrixPoints, {value: 5}),
      yCount: Forms.numberInput(Q.matrixPoints, {value: 5}),
      geometry: h('select', {'aria-label': 'Геометрия ячейки'}, [h('option', {value: 'line'}, 'Векторная линия'), h('option', {value: 'fill'}, 'Залитый участок'),
        h('option', {value: 'text'}, 'Заполненные буквы A8M трёх размеров'),
        h('option', {value: 'vector_text'}, 'Векторные буквы A8M B012 · 2/4 мм × 2')]),
      wobbleStep: Forms.numberInput(Q.wobbleStep, {value: '0.02'}),
    };
    /** The «от» and «до» boxes of an axis: both take what the chosen axis takes, and the lower end lies below the upper (the server says so too). */
    const axisBox = (which, edge, label) => {
      const rule = () => axisRule('matrix', matrix[which + 'Axis'].value);
      return addNumber(`${which}_${edge}`, label, matrix[which + (edge === 'min' ? 'Min' : 'Max')], rule, {card: () => matrixCard,
        after: (r) => {
          if (!r.ok || edge === 'min') return r;
          const low = Forms.parse(matrix[which + 'Min'].value, rule(), {required: true});
          return low.ok && !(low.value < r.value) ? {ok: false, message: `Верхняя граница должна быть выше нижней (${String(low.value).replace('.', ',')}). Введено: ${String(r.value).replace('.', ',')}`} : r;
        }});
    };
    /** The number of points of an axis; the grid has at most 28 cells (the server keeps two layers for the cleaning and the registration). */
    const pointsBox = (which, label) => addFixed(`${which}_count`, label, matrix[which + 'Count'], 'matrixPoints', {card: () => matrixCard,
      after: (r) => {
        if (!r.ok || which === 'x') return r;
        const across = Forms.parse(matrix.xCount.value, Q.matrixPoints, {required: true});
        return across.ok && across.value * r.value > 28 ? {ok: false, message: `В сетке не больше 28 ячеек, сейчас ${across.value} × ${r.value} = ${across.value * r.value}. Уменьшите число точек`} : r;
      }});
    const matrixAxes = Object.entries(MATRIX_AXES).map(([key, value]) => h('option', {value: key}, value.name));
    matrix.xAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.yAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.xAxis.value = 'power'; matrix.yAxis.value = 'speed';
    const matrixCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Как в LightBurn Material Test: две выбранные оси меняются по сетке, остальные параметры остаются постоянными. До 28 ячеек; с чисткой и регистрацией получится не более 30 выходных слоёв.'),
      h('div', {class: 'grid g3'}, field('Ось X', matrix.xAxis), field('Ось Y', matrix.yAxis), field('Геометрия ячейки', matrix.geometry)),
      h('div', {class: 'grid g3'}, axisBox('x', 'min', 'X: от'), axisBox('x', 'max', 'X: до'), pointsBox('x', 'Точек по X')),
      h('div', {class: 'grid g3'}, axisBox('y', 'min', 'Y: от'), axisBox('y', 'max', 'Y: до'), pointsBox('y', 'Точек по Y')),
      addFixed('wobble_step', 'Шаг wobble (при включении)', matrix.wobbleStep, 'wobbleStep', {card: () => matrixCard}),
      h('p', {class: 'muted small'}, 'Для Q-Pulse используются только ступени из паспорта лазера. Шаг линий действует только для заливки и заполненных букв. Wobble проверяется на векторных линиях и однолинейных буквах.'));
    const grey = {
      rows: h('select', {'aria-label': 'Строки шкал серого'}, GREY_AXES.map((key) => h('option', {value: key}, greyAxisName(key)))),
      rowValues: h('input', {value: GREY_DEFAULTS.rowValues}),
      columns: h('select', {'aria-label': 'Столбцы шкал серого'}, GREY_AXES.map((key) => h('option', {value: key}, greyAxisName(key)))),
      columnValues: h('input', {value: GREY_DEFAULTS.columnValues}),
      min: Forms.numberInput(Q.greyPower, {value: GREY_DEFAULTS.min}),
      max: Forms.numberInput(Q.greyPower, {value: GREY_DEFAULTS.max}),
    };
    grey.rows.value = GREY_DEFAULTS.rows; grey.columns.value = GREY_DEFAULTS.columns;
    const greyCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Каждая полоска — свой слой-изображение LightBurn в режиме градаций серого: 16 ступеней от белого (слева, мощность Min) до чёрного (справа, мощность Max). '
        + 'Строки и столбцы меняют два постоянных параметра; остальные берутся из «Основных параметров опыта». До 7 строк и 4 столбцов.'),
      h('div', {class: 'grid g2'}, field('Строки: параметр', grey.rows),
        addList('row_values', 'Значения строк', grey.rowValues, () => axisRule('grey', grey.rows.value), {card: () => greyCard, max: 7, distinct: true})),
      h('div', {class: 'grid g2'}, field('Столбцы: параметр', grey.columns),
        addList('column_values', 'Значения столбцов', grey.columnValues, () => axisRule('grey', grey.columns.value), {card: () => greyCard, max: 4, distinct: true})),
      h('div', {class: 'grid g2'}, addFixed('min_power', 'Min мощность (белый)', grey.min, 'greyPower', {card: () => greyCard}),
        addFixed('max_power', 'Max мощность (чёрный)', grey.max, 'greyPower', {card: () => greyCard,
          after: (r) => {
            const low = Forms.parse(grey.min.value, Q.greyPower, {required: true});
            return r.ok && low.ok && !(low.value < r.value) ? {ok: false, message: `Max должна быть больше Min (${String(low.value).replace('.', ',')}). Введено: ${String(r.value).replace('.', ',')}`} : r;
          }})),
      h('p', {class: 'muted small'}, 'Шаг линий 0,0127 / 0,0169 / 0,0212 / 0,0254 мм — это 2000 / 1500 / 1200 / 1000 dpi. После фотографии каждая полоска станет шкалой «серый → цвет» в разделе «Фотогравировка».'),
      h('p', {class: 'muted small'}, 'Ширина полоски, мм — длина её строк: ступень — 1/16 ширины, не уже 1 мм (ширина от 16 мм). Без этой оси ширина полосок подбирается под предельную ширину платы, не больше 40 мм.'));
    const fill = {
      widths: h('input', {value: FILL_WIDTHS}),
      axis: h('select', {'aria-label': 'Параметр рецептов заливки'}, FILL_AXES.map((key) => h('option', {value: key}, MATRIX_AXES[key].name))),
      values: h('input', {placeholder: 'Пусто — один рецепт; например: 20, 40, 60'}),
    };
    const fillCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Каждая полоска — свой слой заливки LightBurn (Scan) высотой 4 мм при постоянной мощности. Строки идут вдоль полоски, поэтому её ширина — длина строки. '
        + 'Рецепт — «Основные параметры опыта»; рецептов столько, сколько значений меняемого параметра. До 7 рецептов и 5 ширин, не больше 28 полосок.'),
      addList('fill_widths', 'Ширины полосок заливки', fill.widths, () => Q.fillWidth, {card: () => fillCard, max: 5, distinct: true}),
      h('div', {class: 'grid g2'}, field('Рецепты: меняемый параметр', fill.axis),
        addList('fill_recipes', 'Значения рецептов заливки', fill.values, () => axisRule('recipe', fill.axis.value), {card: () => fillCard, optional: true, max: 7})));
    // One picture at several settings: copies of an uploaded picture; without copies given the server changes one setting at a time around the base
    const photo = {
      file: h('input', {type: 'file', accept: 'image/png,image/jpeg'}),
      kind: h('select', {'aria-label': 'Вид копий'}, PHOTO_KINDS.map(([key, name]) => h('option', {value: key}, name))),
      size: Forms.numberInput(Q.copySize, {value: '18'}),
      min: Forms.numberInput(Q.copyMinPower, {value: '1'}),
    };
    const photoCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Восемь копий одной картинки рядом, под каждой — полоска серого на тех же настройках. Первая копия — на основных параметрах опыта, '
        + 'у остальных по одному изменению: в виде точками мощность −20 % и +20 %, скорость +40 %, шаг строк ×1,69, поправка ширины точки и два других вида; '
        + 'в градациях серого — Max, Min, шаг строк и скорость. Картинка берётся в настоящем размере: её длинная сторона — размер копии. '
        + 'Удобнее начинать со страницы фотоработы или фотозоны: кнопка «Подобрать настройки: 8 копий» берёт её картинку и настройки.'),
      form.add('picture', 'Картинка копий (PNG или JPEG)', photo.file, {required: true,
        read: () => (skipped({card: () => photoCard}) ? none : (photo.file.files || [])[0] ? {ok: true, value: photo.file.files[0]} : {ok: false, message: 'Выберите картинку для копий (PNG или JPEG): без неё копий не будет'})}),
      h('div', {class: 'grid g3'}, field('Вид первой копии', photo.kind),
        addFixed('copy_mm', 'Размер копии (длинная сторона)', photo.size, 'copySize', {card: () => photoCard}),
        addNumber('copy_min_power', 'Min мощность копий (градации серого)', photo.min, () => {
          const power = Number(settings.power.value);
          return Number.isFinite(power) && power > 0 ? {...Q.copyMinPower, max: power, maxOpen: true} : Q.copyMinPower;
        }, {card: () => photoCard, when: () => photo.kind.value === 'grayscale'})));
    const settings = {
      power: Forms.numberInput(Q.platePower, {value: DEFAULTS.power}),
      frequency: h('input', {type: 'number', step: 'any', inputmode: 'decimal', value: DEFAULTS.frequency}),
      speed: Forms.numberInput(Q.plateSpeed, {value: DEFAULTS.speed}),
      pulse: h('select', {'aria-label': 'Длительность импульса'}),
      interval: Forms.numberInput(Q.plateInterval, {value: DEFAULTS.line_interval}),
      passes: Forms.numberInput(Q.platePasses, {value: DEFAULTS.passes}),
      global: Forms.numberInput(Q.platePasses, {value: DEFAULTS.global_passes}),
    };
    // 200 нс — только начальное значение, и только если лазер даёт такую ступень; иначе длительность выбирает оператор (DEC-043)
    const pulseOptions = (laser, chosen) => {
      const steps = laser?.passport?.pulse_steps || [];
      const active = steps.find((p) => +p.pulse_width_ns === +chosen) || null;
      settings.pulse.replaceChildren(h('option', {value: '', selected: !active}, 'выберите'),
        ...steps.map((p) => h('option', {value: p.pulse_width_ns, selected: p === active}, `${p.pulse_width_ns} нс${p.cutoff_khz == null ? ' · CW' : ` · срез ${p.cutoff_khz} кГц`}`)));
      settings.pulse.value = active ? String(active.pulse_width_ns) : '';
    };
    const matrixRange = (axis, laser) => {
      const d = MATRIX_AXES[axis];
      if (axis === 'frequency') {
        const r = laser?.passport?.repetition_rate_khz || {min: 1, max: 4000};
        const range = [Math.max(d.min, +r.min), Math.min(d.max, +r.max)];
        return range[0] < range[1] ? range : [+r.min, +r.max];
      }
      if (axis === 'pulse_width') {
        const steps = (laser?.passport?.pulse_steps || []).map((x) => +x.pulse_width_ns).filter(Number.isFinite).sort((a, b) => a - b);
        return steps.length ? [steps[0], steps[steps.length - 1]] : [200, 500];
      }
      return [d.min, d.max];
    };
    const updateMatrixRange = (which) => {
      const laser = available.find((d) => String(d.id) === device.value) || available[0];
      const axis = matrix[which + 'Axis'].value;
      const [min, max] = matrixRange(axis, laser);
      matrix[which + 'Min'].value = min;
      matrix[which + 'Max'].value = max;
    };
    const updateMatrixAxes = (changed) => {
      if (matrix.xAxis.value === matrix.yAxis.value) {
        const other = changed === 'xAxis' ? 'yAxis' : 'xAxis';
        const alternate = Object.keys(MATRIX_AXES).find((key) => key !== matrix[changed].value && key !== matrix[other].value);
        matrix[(changed === 'xAxis' ? 'yAxis' : 'xAxis')].value = alternate;
        updateMatrixRange(changed === 'xAxis' ? 'y' : 'x');
      }
      if ([matrix.xAxis.value, matrix.yAxis.value].includes('line_interval') && ['line', 'vector_text'].includes(matrix.geometry.value)) matrix.geometry.value = 'fill';
      if ([matrix.xAxis.value, matrix.yAxis.value].includes('wobble_size') && ['fill', 'text'].includes(matrix.geometry.value)) matrix.geometry.value = 'vector_text';
      updateMatrixRange(changed === 'xAxis' ? 'x' : 'y');
    };
    type.replaceChildren(h('option', {value: '', selected: true}, 'выберите тип платы'),
      ...typeRows.map((item) => h('option', {value: item.id}, item.name)));

    const fillHardware = () => {
      const laser = available.find((d) => String(d.id) === device.value) || available[0];
      if (!laser) {
        hardware.textContent = 'Добавьте лазер и установите на него линзу в разделе «Лазеры».';
        return;
      }
      const lens = laser.lens;
      hardware.textContent = `Плата делается с линзой, установленной на выбранном лазере: ${App.lensLabel(lens)}${lens.field_mm ? ` · поле ${lens.field_mm} мм` : ''}.`;
      const range = laser.passport?.repetition_rate_khz || {min: 1, max: 4000};
      settings.frequency.value = Math.min(Math.max(DEFAULTS.frequency, range.min), range.max);
      pulseOptions(laser, DEFAULTS.pulse_width);
      updateMatrixRange('x'); updateMatrixRange('y');
    };
    const changeDescription = (resetSize = false) => {
      const item = typeRows.find((row) => row.id === type.value);
      matrixCard.style.display = type.value === 'material_matrix' ? '' : 'none';
      smallCard.style.display = type.value === 'small_patches' ? '' : 'none';
      greyCard.style.display = type.value === 'grey_scales' ? '' : 'none';
      fillCard.style.display = type.value === 'fill_sizes' ? '' : 'none';
      photoCard.style.display = type.value === 'photo_variations' ? '' : 'none';
      // полоски заливки до 100 мм вместе с подписями и метками шире 100 мм
      if (resetSize) maxWidth.value = maxHeight.value = type.value === 'small_patches' ? '25' : type.value === 'fill_sizes' ? '150' : '100';
      if (resetSize && type.value === 'grey_scales') {
        settings.speed.value = GREY_DEFAULTS.speed;
        settings.interval.value = GREY_DEFAULTS.interval;
        const laser = available.find((d) => String(d.id) === device.value) || available[0];
        const range = laser?.passport?.repetition_rate_khz || {min: 1, max: 4000};
        settings.frequency.value = Math.min(Math.max(GREY_DEFAULTS.frequency, range.min), range.max);
      }
      if (type.value === 'small_patches') patchDefaults();
      desc.replaceChildren(...(item ? type.value === 'small_patches' ? [
        h('div', {}, item.purpose),
        h('details', {}, h('summary', {}, 'Подробнее о тесте'),
          h('p', {}, item.action), h('p', {}, item.finds)),
      ] : [
        h('div', {}, h('strong', {}, 'Зачем: '), item.purpose),
        h('div', {}, h('strong', {}, 'Что делает плата: '), item.action),
        h('div', {}, h('strong', {}, 'Что выясняет результат: '), item.finds),
      ] : []));
      if (type.value === 'frequency') {
        const laser = available.find((d) => String(d.id) === device.value) || available[0];
        const cw = laser?.passport?.pulse_steps?.find((p) => p.cutoff_khz == null);
        if (cw) { pulseOptions(laser, cw.pulse_width_ns); settings.pulse.value = cw.pulse_width_ns; }
      }
    };
    device.addEventListener('change', () => { fillHardware(); changeDescription(); refreshRules(); });
    type.addEventListener('change', () => changeDescription(true));
    matrix.xAxis.addEventListener('change', () => updateMatrixAxes('xAxis'));
    matrix.yAxis.addEventListener('change', () => updateMatrixAxes('yAxis'));
    patch.count.addEventListener('change', patchDefaults);
    patch.axis.addEventListener('change', patchDefaults);
    for (const choice of [matrix.xAxis, matrix.yAxis, grey.rows, grey.columns, fill.axis, patch.axis]) choice.addEventListener('change', () => refreshRules());   // the words follow the axis
    settings.power.addEventListener('input', () => refreshRules());                                         // a copy's Min lies below the plate's power
    // a new test starts on the laser and titanium new work starts from (ux-work-creation-p0 REQ-001) unless the caller names others
    const start = preset.device != null || preset.material != null ? {} : await App.contextStart({});
    const laserWanted = preset.device ?? start.device, stockWanted = preset.material ?? start.material;
    if (laserWanted != null && available.some((d) => String(d.id) === String(laserWanted))) device.value = String(laserWanted);
    if (stockWanted != null && stockWanted !== '') material.value = String(stockWanted);
    fillHardware(); changeDescription();
    if (preset.type && typeRows.some((row) => row.id === preset.type)) { type.value = preset.type; changeDescription(true); }

    const newMaterial = {
      name: h('input', {placeholder: 'Например: лист Grade 2'}),
      family: h('input', {value: 'Titanium', placeholder: 'Titanium, Steel, Brass…'}),
      grade: h('input', {placeholder: 'Grade 2, Ti-6Al-4V…'}),
      batch: h('input', {placeholder: 'номер партии или листа'}),
    };
    const stockNotice = Forms.notice({what: 'Запись заготовки', kept: 'Введённое осталось в форме.'});       // beside the form of the new stock, not in a toast
    const addMaterial = async () => {
      stockNotice.clear();
      try {
        const saved = await post('/materials', {name: newMaterial.name.value.trim(), family: newMaterial.family.value.trim(), grade: newMaterial.grade.value.trim() || null,
          batch: newMaterial.batch.value.trim() || null, thickness_mm: null, surface: null});
        material.value = saved.id;                       // the new record is the one chosen
        newMaterial.name.value = newMaterial.grade.value = newMaterial.batch.value = '';
        toast('Заготовка сохранена и выбрана', 'ok');
      } catch (e) { stockNotice.fail(e); }
    };

    // REQ-020: для какой задачи гравировки делается плата; по умолчанию — что исследует её тип (буквы — надписи, линии — линии…)
    const task = Tasks.chooser('', {empty: 'по типу платы', hint: 'каждая ячейка записывает и свою задачу: буквы — надписи, остальное — по режиму LightBurn'});
    const typeField = form.add('test_type', 'Тип экспериментальной платы', type, {required: true,
      read: () => (type.value ? {ok: true, value: type.value} : {ok: false, message: 'Выберите тип экспериментальной платы'})});
    const deviceField = form.add('device_id', 'Лазер', device, {required: true,
      read: () => { const laser = available.find((d) => String(d.id) === device.value); return laser ? {ok: true, value: +laser.id} : {ok: false, message: 'Выберите лазер с установленной линзой'}; }});
    const materialField = form.add('material_id', 'Заготовка', material, {required: true,
      read: () => (material.value ? {ok: true, value: +material.value} : {ok: false, message: 'Выберите конкретную заготовку: лист или партию, не марку'})});
    const sizeFields = [addFixed('max_width_mm', 'Максимальная ширина платы', maxWidth, 'plateSize'), addFixed('max_height_mm', 'Максимальная высота платы', maxHeight, 'plateSize')];
    const settingFields = [
      addFixed('power', 'Базовая мощность', settings.power, 'platePower'),
      addNumber('frequency', 'Базовая частота', settings.frequency, frequencyRule),
      addFixed('speed', 'Базовая скорость', settings.speed, 'plateSpeed'),
      form.add('pulse_width', 'Q-Pulse', settings.pulse, {required: true, unit: 'нс',
        read: () => (settings.pulse.value === '' ? {ok: false, message: 'Выберите длительность импульса Q-Pulse из ступеней лазера'} : {ok: true, value: +settings.pulse.value})}),
      addFixed('line_interval', 'Интервал линий', settings.interval, 'plateInterval'),
      addFixed('passes', 'Проходы слоя', settings.passes, 'platePasses'),
      addFixed('global_passes', 'Глобальные проходы', settings.global, 'platePasses')];
    const body = h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'Выбери тест, лазер и заготовку. Рецепт предварительной очистки пока задан для титана.'),
      typeField, desc, task.el,
      deviceField, hardware,
      materialField,
      h('div', {class: 'grid g2'}, ...sizeFields),
      matrixCard, smallCard, greyCard, fillCard, photoCard,
      h('details', {class: 'card'}, h('summary', {}, 'Добавить новую заготовку'),
        h('div', {class: 'stack', style: 'margin-top:12px'},
          h('div', {class: 'grid g3'}, field('Материал', newMaterial.family), field('Название / лист', newMaterial.name), field('Марка / сплав', newMaterial.grade), field('Партия', newMaterial.batch)),
          stockNotice.error, btn('Сохранить заготовку', addMaterial))),
      h('details', {class: 'card'}, h('summary', {}, 'Основные параметры опыта'),
        h('p', {class: 'muted small'}, 'Эти значения — настройки этой платы и сохраняются с ней. Тип платы сам перебирает указанные в описании оси; поля задают остальные условия. Для матрицы выбранные оси переопределяют соответствующие базовые значения. Для частотного теста выбирается CW-ступень, если она указана в паспорте.'),
        h('div', {class: 'grid g3'}, ...settingFields)),
      h('details', {class: 'card'}, h('summary', {}, 'Параметры очистки и меток'),
        h('p', {class: 'muted small'}, 'В каждом LightBurn-файле первым будет слой чистки: 20% / 48 кГц / 2000 мм/с, Q-Pulse 200 нс, шаг 0,05 мм, один проход слоя и один глобальный проход, двунаправленно и cross-hatch. Затем идут чёрные подписи/метки и тестовые слои. Для выбранного лазера чистка автоматически подстраивается только если паспорт не поддерживает 48 кГц или 200 нс.')));

    /** The body of the request, or null when a box is wrong (each wrong box is marked beside itself and keeps what was typed). */
    const requestBody = () => {
      const v = form.collect();
      if (!v) return null;
      const out = {device_id: v.device_id, material_id: v.material_id, test_type: v.test_type,
        power: v.power, frequency: v.frequency, speed: v.speed, pulse_width: v.pulse_width, line_interval: v.line_interval,
        passes: v.passes, global_passes: v.global_passes, max_width_mm: v.max_width_mm, max_height_mm: v.max_height_mm, split_if_needed: true, ...task.body()};
      if (v.test_type === 'material_matrix') {
        out.matrix = {x_axis: matrix.xAxis.value, y_axis: matrix.yAxis.value, geometry: matrix.geometry.value, wobble_step: v.wobble_step,
          x_min: v.x_min, x_max: v.x_max, x_count: v.x_count, y_min: v.y_min, y_max: v.y_max, y_count: v.y_count};
      }
      if (v.test_type === 'grey_scales') {
        out.power = v.max_power;
        out.scales = {rows: {axis: grey.rows.value, values: v.row_values}, columns: {axis: grey.columns.value, values: v.column_values},
          min_power: v.min_power, max_power: v.max_power};
      }
      if (v.test_type === 'fill_sizes') {
        out.widths_mm = v.fill_widths;
        out.recipes = v.fill_recipes ? v.fill_recipes.map((value) => ({[fill.axis.value]: value})) : [{}];
      }
      if (v.test_type === 'photo_variations') {
        out.variations = {picture_name: v.picture.name, dither: photo.kind.value, copy_mm: v.copy_mm,
          ...(photo.kind.value === 'grayscale' ? {min_power: v.copy_min_power} : {})};
      }
      if (v.test_type === 'small_patches') {
        const count = +patch.count.value;
        out.patch_size_mm = +patch.size.value;
        out.registration = patch.registration.value;
        out.patches = count === 1 ? [{}] : v.patch_values.map((value) => ({[patch.axis.value]: value}));
      }
      return out;
    };
    smallCard.append(btn('Показать размер', async () => {
      try {
        const sent = requestBody();
        if (!sent) return;
        const result = await post('/capability-plates/preview', sent);
        form.clear();
        const parts = result.parts || [{summary: result.summary, output_layers: result.output_layers}];
        previewText.replaceChildren(...parts.map((part, index) => {
          const size = part.summary.size_mm;
          return h('div', {}, `Часть ${index + 1}/${parts.length}: ${size.width} × ${size.height} мм · `,
            `${part.summary.registration === 'full' ? 'QR и метки' : 'без меток'} · `,
            `${part.summary.test_features} квадрат(а) · ${part.output_layers} выходных слоя · `,
            `очистка ${part.summary.clean_area_mm2} мм²`, placement(part.summary));
        }));
      } catch (e) { form.fail(e); }
    }));
    body.append(form.error);                         // above the buttons, where what the server refuses is said with what to do next
    refreshRules();

    return modal('Создать экспериментальную плату', body, [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Создать плату', cls: 'primary', run: async (x) => {
        const sent = requestBody();
        if (!sent) return;                            // a wrong box is marked beside itself; the dialog stays open with everything typed
        let made;
        try {
          if (sent.variations) sent.variations.picture_png = await base64Of(photo.file.files[0]);
          made = await post('/capability-plates', sent);
        } catch (e) { form.fail(e); return; }
        const through = available.find((d) => d.id === sent.device_id);         // the next new work and test start where this test was made
        App.rememberContext({device: sent.device_id, lens: through && through.lens ? through.lens.id : null, material: sent.material_id});
        x.close();
        if (reload) reload();
        const parts = made.parts || [made];
        if (parts.length === 1) {
          const unchecked = parts[0].summary.work_field && !parts[0].summary.work_field.checked;
          toast(`Создано: ${parts[0].name} · ${parts[0].summary.layers} тестовых слоёв${unchecked ? ' · ' + UNCHECKED : ''}`, unchecked ? 'warn' : 'ok');
          go('/experiment/plan-' + parts[0].plan_id);
        } else {
          modal('Части компактного теста', h('div', {class: 'stack'},
            h('p', {}, `Создано ${parts.length} самостоятельных LightBurn-файла. Каждый начинается с локальной чистки${parts[0].summary.registration === 'full' ? ' и имеет собственные метки' : ''}.`),
            ...parts.map((part, index) => h('div', {class: 'card row'},
              h('strong', {}, `Часть ${index + 1}/${parts.length} · квадраты ${part.sample_indexes.join(', ')}`), placement(part.summary),
              h('span', {class: 'spacer'}),
              h('a', {href: part.download_url, download: ''}, 'Скачать LightBurn'),
              h('a', {href: '#/plans/' + part.plan_id}, 'Открыть план')))),
          [{label: 'Закрыть', run: (dialog) => dialog.close()}]);
        }
      }},
    ]);
  }

  return {open};
})();
