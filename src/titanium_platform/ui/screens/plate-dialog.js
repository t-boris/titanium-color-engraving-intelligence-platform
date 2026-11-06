/* Create an experiment plate with its laser and material. */
'use strict';
const PlateDialog = (() => {
  const {h, btn, field, get, post, toast, modal, go} = App;
  const UNCHECKED = 'lens field unknown — placement not checked';

  /** Check placement against the laser and lens working field; an unknown field is unchecked. */
  function placementText(summary) {
    const w = summary && summary.work_field;
    if (!w) return '';
    return w.checked ? `fits within the working field ${w.field_mm.width} × ${w.field_mm.height} mm` : UNCHECKED;
  }
  const placement = (summary) => {
    const text = placementText(summary);
    return text ? h('span', {class: summary.work_field.checked ? 'muted' : 'pill warn'}, ` · ${text}`) : null;
  };

  const DEFAULTS = {power: 20, frequency: 48, speed: 900, pulse_width: 200, line_interval: 0.025, passes: 1, global_passes: 1};
  const MATRIX_AXES = {
    power: {name: 'Power, %', min: 5, max: 100}, speed: {name: 'Speed, mm/s', min: 500, max: 10000},
    frequency: {name: 'Frequency, kHz', min: 24, max: 96}, pulse_width: {name: 'Q-Pulse, ns', min: 2, max: 500},
    line_interval: {name: 'Line interval, mm', min: 0.01, max: 0.2}, passes: {name: 'Passes', min: 1, max: 5},
    wobble_size: {name: 'Wobble diameter, mm (0 = off)', min: 0, max: 0.08},
  };
  // REQ-059: grayscale scales use two axes from these parameters and strip width; rows default to line interval and columns to speed
  const GREY_AXES = ['line_interval', 'speed', 'frequency', 'pulse_width', 'passes', 'width'];
  const greyAxisName = (key) => key === 'width' ? 'Strip width, mm' : MATRIX_AXES[key].name;
  const GREY_DEFAULTS = {rows: 'line_interval', rowValues: '0.0127, 0.0169, 0.0212, 0.0254', columns: 'speed', columnValues: '100, 150, 250',
    min: 1, max: 40, speed: 150, frequency: 60, interval: 0.0169};
  // Fill size: strips of these widths for each recipe, varying one base setting
  const FILL_AXES = ['power', 'speed', 'frequency', 'pulse_width', 'line_interval', 'passes'];
  const FILL_WIDTHS = '5, 20, 50, 100';
  const PHOTO_KINDS = [['jarvis', 'Jarvis'], ['atkinson', 'Atkinson'], ['stucki', 'Stucki'], ['grayscale', 'Grayscale']];
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
      const el = form.add(name, label, input, {required: true, help: 'allowed values depend on the selected laser and parameter',
        read: () => (skipped(o) ? none : (o.after || ((r) => r))(Forms.readNumber(input, rule(), {required: true})))});
      dynamic.push({el, words: () => Forms.rulesText(rule())});
      return el;
    };
    /** A number box whose rule is fixed (a quantity of forms.js). */
    const addFixed = (name, label, input, quantity, o = {}) => form.add(name, label, input, {quantity, required: true,
      read: () => (skipped(o) ? none : (o.after || ((r) => r))(Forms.readNumber(input, Q[quantity], {required: true})))});
    /** Numbers typed with commas («5, 20, 50»): each is read by ``rule``; ``o.max`` is how many the plate takes, ``o.distinct`` that no two are alike. */
    const addList = (name, label, input, rule, o = {}) => {
      const el = form.add(name, label, input, {required: !o.optional, help: 'comma-separated numbers', read: () => {
        if (skipped(o)) return none;
        const parts = input.value.split(/[,;\s]+/).filter(Boolean);
        if (!parts.length) return o.optional ? none : {ok: false, message: 'Complete this field'};
        const values = [];
        for (const [i, part] of parts.entries()) {
          const r = Forms.parse(part, rule(), {required: true});
          if (!r.ok) return {ok: false, message: `Value ${i + 1}: ${r.message}`};
          values.push(r.value);
        }
        if (o.max && values.length > o.max) return {ok: false, message: `At most ${o.max} values. Entered: ${values.length}`};
        if (o.distinct && new Set(values).size !== values.length) return {ok: false, message: 'Values must be distinct'};
        return (o.after || ((r) => r))({ok: true, value: values});
      }});
      dynamic.push({el, words: () => `${Forms.rulesText(rule())} · comma-separated numbers${o.max ? `, at most ${o.max}` : ''}${o.distinct ? ', all distinct' : ''}`});
      return el;
    };
    const type = h('select', {'aria-label': 'Experiment plate type'}, h('option', {value: '', selected: true}, 'select a plate type'));
    const device = h('select', {'aria-label': 'Laser'}, available.map((d) => h('option', {value: d.id}, `${d.name}${d.serial ? ` · ${d.serial}` : ''}`)));
    // nothing is chosen until the caller or the workshop's last choice names a record (below); one concrete batch or sheet, never a grade
    const material = MaterialPicker.create({allowEmpty: true, clearLabel: 'Clear selection', empty: 'select a specific blank', title: 'Select a blank for the plate', name: 'Blank'});
    const desc = h('div', {class: 'stack muted small'});
    const hardware = h('p', {class: 'muted small'});
    const maxWidth = Forms.numberInput(Q.plateSize, {value: '100'});
    const maxHeight = Forms.numberInput(Q.plateSize, {value: '100'});
    const patch = {
      count: h('select', {'aria-label': 'Number of squares'}, [1, 2, 4].map((n) => h('option', {value: n}, String(n)))),
      size: h('select', {'aria-label': 'Square size'}, [3, 5].map((n) => h('option', {value: n}, `${n} × ${n} mm`))),
      registration: h('select', {'aria-label': 'Photo registration'}, [h('option', {value: 'none'}, 'No markers · minimum area'),
        h('option', {value: 'full'}, 'QR + 4 markers · easier photo alignment')]),
      axis: h('select', {'aria-label': 'Vary parameter'}, ['power', 'speed', 'frequency', 'pulse_width', 'line_interval', 'passes']
        .map((key) => h('option', {value: key}, MATRIX_AXES[key].name))),
      values: h('input', {placeholder: 'For example: 5, 20, 50, 100'}),
    };
    const patchSweep = h('div', {class: 'grid g2'}, field('Vary parameter', patch.axis),
      addList('patch_values', 'Square values, left to right', patch.values, () => axisRule('recipe', patch.axis.value), {card: () => smallCard, when: () => +patch.count.value > 1,
        after: (r) => (r.ok && r.value.length !== +patch.count.value ? {ok: false, message: `Exactly ${patch.count.value} numbers are required for ${patch.count.value} squares. Entered: ${r.value.length}`} : r)}));
    const previewText = h('div', {class: 'muted small', 'aria-live': 'polite'},
      'Size is shown before file creation; each file cleans only its own area.');
    const smallCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'One to four squares. If they do not fit together, separate LightBurn files are created. No markers minimizes area but photo alignment may require manual adjustment.'),
      h('div', {class: 'grid g3'}, field('Number of squares', patch.count), field('Square size', patch.size),
        field('Photo registration', patch.registration)),
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
      previewText.textContent = 'Size is shown before file creation; each file cleans only its own area.';
    };
    const matrix = {
      xAxis: h('select', {'aria-label': 'Matrix X axis'}), yAxis: h('select', {'aria-label': 'Matrix Y axis'}),
      xMin: h('input', {type: 'number', step: 'any', value: 5}), xMax: h('input', {type: 'number', step: 'any', value: 100}),
      yMin: h('input', {type: 'number', step: 'any', value: 500}), yMax: h('input', {type: 'number', step: 'any', value: 10000}),
      xCount: Forms.numberInput(Q.matrixPoints, {value: 5}),
      yCount: Forms.numberInput(Q.matrixPoints, {value: 5}),
      geometry: h('select', {'aria-label': 'Cell geometry'}, [h('option', {value: 'line'}, 'Vector line'), h('option', {value: 'fill'}, 'Filled area'),
        h('option', {value: 'text'}, 'Filled A8M letters in three sizes'),
        h('option', {value: 'vector_text'}, 'Vector A8M B012 letters · 2/4 mm × 2')]),
      wobbleStep: Forms.numberInput(Q.wobbleStep, {value: '0.02'}),
    };
    /** The “from” and “to” boxes of an axis: both take what the chosen axis takes, and the lower end lies below the upper (the server says so too). */
    const axisBox = (which, edge, label) => {
      const rule = () => axisRule('matrix', matrix[which + 'Axis'].value);
      return addNumber(`${which}_${edge}`, label, matrix[which + (edge === 'min' ? 'Min' : 'Max')], rule, {card: () => matrixCard,
        after: (r) => {
          if (!r.ok || edge === 'min') return r;
          const low = Forms.parse(matrix[which + 'Min'].value, rule(), {required: true});
          return low.ok && !(low.value < r.value) ? {ok: false, message: `The upper bound must exceed the lower bound (${String(low.value).replace('.', ',')}). Entered: ${String(r.value).replace('.', ',')}`} : r;
        }});
    };
    /** The number of points of an axis; the grid has at most 28 cells (the server keeps two layers for the cleaning and the registration). */
    const pointsBox = (which, label) => addFixed(`${which}_count`, label, matrix[which + 'Count'], 'matrixPoints', {card: () => matrixCard,
      after: (r) => {
        if (!r.ok || which === 'x') return r;
        const across = Forms.parse(matrix.xCount.value, Q.matrixPoints, {required: true});
        return across.ok && across.value * r.value > 28 ? {ok: false, message: `The grid supports at most 28 cells; currently ${across.value} × ${r.value} = ${across.value * r.value}. Reduce the number of points`} : r;
      }});
    const matrixAxes = Object.entries(MATRIX_AXES).map(([key, value]) => h('option', {value: key}, value.name));
    matrix.xAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.yAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.xAxis.value = 'power'; matrix.yAxis.value = 'speed';
    const matrixCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'As in LightBurn Material Test, two selected axes vary across the grid while other settings stay fixed. Up to 28 cells produce at most 30 output layers including cleaning and registration.'),
      h('div', {class: 'grid g3'}, field('X axis', matrix.xAxis), field('Y axis', matrix.yAxis), field('Cell geometry', matrix.geometry)),
      h('div', {class: 'grid g3'}, axisBox('x', 'min', 'X: from'), axisBox('x', 'max', 'X: to'), pointsBox('x', 'X points')),
      h('div', {class: 'grid g3'}, axisBox('y', 'min', 'Y: from'), axisBox('y', 'max', 'Y: to'), pointsBox('y', 'Y points')),
      addFixed('wobble_step', 'Wobble step (when enabled)', matrix.wobbleStep, 'wobbleStep', {card: () => matrixCard}),
      h('p', {class: 'muted small'}, 'Q-Pulse uses only steps listed in the laser specifications. Line interval applies to fills and filled letters; wobble is tested on vector lines and single-line letters.'));
    const grey = {
      rows: h('select', {'aria-label': 'Grayscale scale rows'}, GREY_AXES.map((key) => h('option', {value: key}, greyAxisName(key)))),
      rowValues: h('input', {value: GREY_DEFAULTS.rowValues}),
      columns: h('select', {'aria-label': 'Grayscale scale columns'}, GREY_AXES.map((key) => h('option', {value: key}, greyAxisName(key)))),
      columnValues: h('input', {value: GREY_DEFAULTS.columnValues}),
      min: Forms.numberInput(Q.greyPower, {value: GREY_DEFAULTS.min}),
      max: Forms.numberInput(Q.greyPower, {value: GREY_DEFAULTS.max}),
    };
    grey.rows.value = GREY_DEFAULTS.rows; grey.columns.value = GREY_DEFAULTS.columns;
    const greyCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Each strip is a separate LightBurn grayscale image layer with 16 steps from white (left, Min power) to black (right, Max power). '
        + 'Rows and columns vary two fixed parameters; the others use the base experiment settings. Up to 7 rows and 4 columns.'),
      h('div', {class: 'grid g2'}, field('Rows: parameter', grey.rows),
        addList('row_values', 'Row values', grey.rowValues, () => axisRule('grey', grey.rows.value), {card: () => greyCard, max: 7, distinct: true})),
      h('div', {class: 'grid g2'}, field('Columns: parameter', grey.columns),
        addList('column_values', 'Column values', grey.columnValues, () => axisRule('grey', grey.columns.value), {card: () => greyCard, max: 4, distinct: true})),
      h('div', {class: 'grid g2'}, addFixed('min_power', 'Min power (white)', grey.min, 'greyPower', {card: () => greyCard}),
        addFixed('max_power', 'Max power (black)', grey.max, 'greyPower', {card: () => greyCard,
          after: (r) => {
            const low = Forms.parse(grey.min.value, Q.greyPower, {required: true});
            return r.ok && low.ok && !(low.value < r.value) ? {ok: false, message: `Max must be greater than Min (${String(low.value).replace('.', ',')}). Entered: ${String(r.value).replace('.', ',')}`} : r;
          }})),
      h('p', {class: 'muted small'}, 'Line intervals 0.0127 / 0.0169 / 0.0212 / 0.0254 mm correspond to 2000 / 1500 / 1200 / 1000 dpi. After photographing, each strip becomes a grayscale-to-color scale in Photo engraving.'),
      h('p', {class: 'muted small'}, 'Strip width is its line length: each step is 1/16 of the width and at least 1 mm (minimum width 16 mm). Without this axis, strip width fits the plate limit and is no greater than 40 mm.'));
    const fill = {
      widths: h('input', {value: FILL_WIDTHS}),
      axis: h('select', {'aria-label': 'Fill recipe parameter'}, FILL_AXES.map((key) => h('option', {value: key}, MATRIX_AXES[key].name))),
      values: h('input', {placeholder: 'Leave empty for one recipe; for example: 20, 40, 60'}),
    };
    const fillCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Each strip is a 4 mm-high LightBurn fill layer (Scan) at constant power. Lines run along the strip, so its width is the line length. '
        + 'Recipes use base experiment settings, with one recipe per varied parameter value. Up to 7 recipes and 5 widths, with at most 28 strips.'),
      addList('fill_widths', 'Fill strip widths', fill.widths, () => Q.fillWidth, {card: () => fillCard, max: 5, distinct: true}),
      h('div', {class: 'grid g2'}, field('Recipes: varied parameter', fill.axis),
        addList('fill_recipes', 'Fill recipe values', fill.values, () => axisRule('recipe', fill.axis.value), {card: () => fillCard, optional: true, max: 7})));
    // One picture at several settings: copies of an uploaded picture; without copies given the server changes one setting at a time around the base
    const photo = {
      file: h('input', {type: 'file', accept: 'image/png,image/jpeg'}),
      kind: h('select', {'aria-label': 'Copy mode'}, PHOTO_KINDS.map(([key, name]) => h('option', {value: key}, name))),
      size: Forms.numberInput(Q.copySize, {value: '18'}),
      min: Forms.numberInput(Q.copyMinPower, {value: '1'}),
    };
    const photoCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Eight copies of one image, each with a grayscale strip using the same settings. The first copy uses base experiment settings; '
        + 'each other copy changes one setting: in dot mode, power −20% and +20%, speed +40%, line interval ×1.69, dot width correction, and two other modes; '
        + 'in grayscale, Max, Min, line interval, and speed. The image is used at actual size, with its long side equal to the copy size. '
        + 'Start from a photo work or photo zone to use its image and settings with Find settings: 8 copies.'),
      form.add('picture', 'Copy image (PNG or JPEG)', photo.file, {required: true,
        read: () => (skipped({card: () => photoCard}) ? none : (photo.file.files || [])[0] ? {ok: true, value: photo.file.files[0]} : {ok: false, message: 'Select an image for the copies (PNG or JPEG).'})}),
      h('div', {class: 'grid g3'}, field('First copy mode', photo.kind),
        addFixed('copy_mm', 'Copy size (long side)', photo.size, 'copySize', {card: () => photoCard}),
        addNumber('copy_min_power', 'Copy Min power (grayscale)', photo.min, () => {
          const power = Number(settings.power.value);
          return Number.isFinite(power) && power > 0 ? {...Q.copyMinPower, max: power, maxOpen: true} : Q.copyMinPower;
        }, {card: () => photoCard, when: () => photo.kind.value === 'grayscale'})));
    const settings = {
      power: Forms.numberInput(Q.platePower, {value: DEFAULTS.power}),
      frequency: h('input', {type: 'number', step: 'any', inputmode: 'decimal', value: DEFAULTS.frequency}),
      speed: Forms.numberInput(Q.plateSpeed, {value: DEFAULTS.speed}),
      pulse: h('select', {'aria-label': 'Pulse width'}),
      interval: Forms.numberInput(Q.plateInterval, {value: DEFAULTS.line_interval}),
      passes: Forms.numberInput(Q.platePasses, {value: DEFAULTS.passes}),
      global: Forms.numberInput(Q.platePasses, {value: DEFAULTS.global_passes}),
    };
    // 200 ns is only the initial value when the laser supports it; otherwise the operator chooses a pulse width (DEC-043)
    const pulseOptions = (laser, chosen) => {
      const steps = laser?.passport?.pulse_steps || [];
      const active = steps.find((p) => +p.pulse_width_ns === +chosen) || null;
      settings.pulse.replaceChildren(h('option', {value: '', selected: !active}, 'select'),
        ...steps.map((p) => h('option', {value: p.pulse_width_ns, selected: p === active}, `${p.pulse_width_ns} ns${p.cutoff_khz == null ? ' · CW' : ` · cutoff ${p.cutoff_khz} kHz`}`)));
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
    type.replaceChildren(h('option', {value: '', selected: true}, 'select a plate type'),
      ...typeRows.map((item) => h('option', {value: item.id}, item.name)));

    const fillHardware = () => {
      const laser = available.find((d) => String(d.id) === device.value) || available[0];
      if (!laser) {
        hardware.textContent = 'Add a laser and install a lens in the Lasers section.';
        return;
      }
      const lens = laser.lens;
      hardware.textContent = `The plate uses the lens installed on the selected laser: ${App.lensLabel(lens)}${lens.field_mm ? ` · field ${lens.field_mm} mm` : ''}.`;
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
      // fill strips up to 100 mm may exceed 100 mm with labels and markers
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
        h('details', {}, h('summary', {}, 'Test details'),
          h('p', {}, item.action), h('p', {}, item.finds)),
      ] : [
        h('div', {}, h('strong', {}, 'Purpose: '), item.purpose),
        h('div', {}, h('strong', {}, 'What the plate does: '), item.action),
        h('div', {}, h('strong', {}, 'What the result reveals: '), item.finds),
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
      name: h('input', {placeholder: 'For example: Grade 2 sheet'}),
      family: h('input', {value: 'Titanium', placeholder: 'Titanium, Steel, Brass…'}),
      grade: h('input', {placeholder: 'Grade 2, Ti-6Al-4V…'}),
      batch: h('input', {placeholder: 'batch or sheet number'}),
    };
    const stockNotice = Forms.notice({what: 'Save blank', kept: 'Your entries remain in the form.'});       // beside the form of the new stock, not in a toast
    const addMaterial = async () => {
      stockNotice.clear();
      try {
        const saved = await post('/materials', {name: newMaterial.name.value.trim(), family: newMaterial.family.value.trim(), grade: newMaterial.grade.value.trim() || null,
          batch: newMaterial.batch.value.trim() || null, thickness_mm: null, surface: null});
        material.value = saved.id;                       // the new record is the one chosen
        newMaterial.name.value = newMaterial.grade.value = newMaterial.batch.value = '';
        toast('Blank saved and selected', 'ok');
      } catch (e) { stockNotice.fail(e); }
    };

    // REQ-020: engraving task defaults to the plate type’s purpose
    const task = Tasks.chooser('', {empty: 'by plate type', hint: 'each cell records its own task: letters use inscriptions; others use the LightBurn mode'});
    const typeField = form.add('test_type', 'Experiment plate type', type, {required: true,
      read: () => (type.value ? {ok: true, value: type.value} : {ok: false, message: 'Select an experiment plate type'})});
    const deviceField = form.add('device_id', 'Laser', device, {required: true,
      read: () => { const laser = available.find((d) => String(d.id) === device.value); return laser ? {ok: true, value: +laser.id} : {ok: false, message: 'Select a laser with a lens installed'}; }});
    const materialField = form.add('material_id', 'Blank', material, {required: true,
      read: () => (material.value ? {ok: true, value: +material.value} : {ok: false, message: 'Select a specific blank: sheet or batch, not just a grade'})});
    const sizeFields = [addFixed('max_width_mm', 'Maximum plate width', maxWidth, 'plateSize'), addFixed('max_height_mm', 'Maximum plate height', maxHeight, 'plateSize')];
    const settingFields = [
      addFixed('power', 'Base power', settings.power, 'platePower'),
      addNumber('frequency', 'Base frequency', settings.frequency, frequencyRule),
      addFixed('speed', 'Base speed', settings.speed, 'plateSpeed'),
      form.add('pulse_width', 'Q-Pulse', settings.pulse, {required: true, unit: 'ns',
        read: () => (settings.pulse.value === '' ? {ok: false, message: 'Select a Q-Pulse width supported by the laser'} : {ok: true, value: +settings.pulse.value})}),
      addFixed('line_interval', 'Line interval', settings.interval, 'plateInterval'),
      addFixed('passes', 'Layer passes', settings.passes, 'platePasses'),
      addFixed('global_passes', 'Global passes', settings.global, 'platePasses')];
    const body = h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'Select a test, laser, and blank. The cleaning recipe is currently configured for titanium.'),
      typeField, desc, task.el,
      deviceField, hardware,
      materialField,
      h('div', {class: 'grid g2'}, ...sizeFields),
      matrixCard, smallCard, greyCard, fillCard, photoCard,
      h('details', {class: 'card'}, h('summary', {}, 'Add a new blank'),
        h('div', {class: 'stack', style: 'margin-top:12px'},
          h('div', {class: 'grid g3'}, field('Material', newMaterial.family), field('Name / sheet', newMaterial.name), field('Grade / alloy', newMaterial.grade), field('Batch', newMaterial.batch)),
          stockNotice.error, btn('Save blank', addMaterial))),
      h('details', {class: 'card'}, h('summary', {}, 'Base experiment settings'),
        h('p', {class: 'muted small'}, 'These settings are saved with the plate. The plate type varies its described axes; these fields specify the other conditions. Matrix axes override corresponding base values. Frequency tests use the CW step when listed in the specifications.'),
        h('div', {class: 'grid g3'}, ...settingFields)),
      h('details', {class: 'card'}, h('summary', {}, 'Cleaning and marker settings'),
        h('p', {class: 'muted small'}, 'Each LightBurn file starts with a cleaning layer: 20% / 48 kHz / 2000 mm/s, Q-Pulse 200 ns, 0.05 mm interval, one layer pass and one global pass, bidirectional and cross-hatch. Black labels and markers follow, then test layers. Cleaning is adjusted only if the laser does not support 48 kHz or 200 ns.')));

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
    smallCard.append(btn('Show size', async () => {
      try {
        const sent = requestBody();
        if (!sent) return;
        const result = await post('/capability-plates/preview', sent);
        form.clear();
        const parts = result.parts || [{summary: result.summary, output_layers: result.output_layers}];
        previewText.replaceChildren(...parts.map((part, index) => {
          const size = part.summary.size_mm;
          return h('div', {}, `Part ${index + 1}/${parts.length}: ${size.width} × ${size.height} mm · `,
            `${part.summary.registration === 'full' ? 'QR and markers' : 'no markers'} · `,
            `${part.summary.test_features} squares · ${part.output_layers} output layers · `,
            `cleaning ${part.summary.clean_area_mm2} mm²`, placement(part.summary));
        }));
      } catch (e) { form.fail(e); }
    }));
    body.append(form.error);                         // above the buttons, where what the server refuses is said with what to do next
    refreshRules();

    return modal('Create experiment plate', body, [
      {label: 'Cancel', run: (x) => x.close()},
      {label: 'Create plate', cls: 'primary', run: async (x) => {
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
          toast(`Created: ${parts[0].name} · ${parts[0].summary.layers} test layers${unchecked ? ' · ' + UNCHECKED : ''}`, unchecked ? 'warn' : 'ok');
          go('/experiment/plan-' + parts[0].plan_id);
        } else {
          modal('Compact test parts', h('div', {class: 'stack'},
            h('p', {}, `Created ${parts.length} separate LightBurn files. Each starts with local cleaning${parts[0].summary.registration === 'full' ? ' and has its own markers' : ''}.`),
            ...parts.map((part, index) => h('div', {class: 'card row'},
              h('strong', {}, `Part ${index + 1}/${parts.length} · squares ${part.sample_indexes.join(', ')}`), placement(part.summary),
              h('span', {class: 'spacer'}),
              h('a', {href: part.download_url, download: ''}, 'Download LightBurn'),
              h('a', {href: '#/plans/' + part.plan_id}, 'Open plan')))),
          [{label: 'Close', run: (dialog) => dialog.close()}]);
        }
      }},
    ]);
  }

  return {open};
})();
