/* Создание экспериментальной платы: лазер и материал задаются здесь, оборудование хранится в контексте опыта. */
'use strict';
const PlateDialog = (() => {
  const {h, btn, field, get, post, toast, fail, modal, go} = App;

  const DEFAULTS = {power: 20, frequency: 48, speed: 900, pulse_width: 200, line_interval: 0.025, passes: 1, global_passes: 1};
  const MATRIX_AXES = {
    power: {name: 'Мощность, %', min: 5, max: 100}, speed: {name: 'Скорость, мм/с', min: 500, max: 10000},
    frequency: {name: 'Частота, кГц', min: 24, max: 96}, pulse_width: {name: 'Q-Pulse, нс', min: 2, max: 500},
    line_interval: {name: 'Интервал линий, мм', min: 0.01, max: 0.2}, passes: {name: 'Проходы', min: 1, max: 5},
    wobble_size: {name: 'Диаметр wobble, мм (0 = выкл.)', min: 0, max: 0.08},
  };
  const materialName = (m) => [m.family, m.name, m.grade, m.batch && `партия ${m.batch}`].filter(Boolean).join(' · ');

  async function open(devices, materials, reload) {
    const typeRows = await get('/plate-types');
    const available = (devices || []).filter((d) => d.lens);
    const type = h('select', {'aria-label': 'Тип экспериментальной платы'}, h('option', {value: '', selected: true}, 'выберите тип платы'));
    const device = h('select', {'aria-label': 'Лазер'}, available.map((d) => h('option', {value: d.id}, `${d.name}${d.serial ? ` · ${d.serial}` : ''}`)));
    const material = h('select', {'aria-label': 'Заготовка'}, [h('option', {value: ''}, 'выберите конкретную заготовку')].concat((materials || []).map((m) => h('option', {value: m.id}, materialName(m)))));
    const desc = h('div', {class: 'stack muted small'});
    const hardware = h('p', {class: 'muted small'});
    const maxWidth = h('input', {type: 'number', min: '1', max: '100', step: 'any', value: '100'});
    const maxHeight = h('input', {type: 'number', min: '1', max: '100', step: 'any', value: '100'});
    const patch = {
      count: h('select', {}, [1, 2, 4].map((n) => h('option', {value: n}, String(n)))),
      size: h('select', {}, [3, 5].map((n) => h('option', {value: n}, `${n} × ${n} мм`))),
      registration: h('select', {}, [h('option', {value: 'none'}, 'Без меток · минимум площади'),
        h('option', {value: 'full'}, 'QR + 4 метки · проще совместить фото')]),
      axis: h('select', {}, ['power', 'speed', 'frequency', 'pulse_width', 'line_interval', 'passes']
        .map((key) => h('option', {value: key}, MATRIX_AXES[key].name))),
      values: h('input', {placeholder: 'Например: 5, 20, 50, 100'}),
    };
    const patchSweep = h('div', {class: 'grid g2'}, field('Менять параметр', patch.axis),
      field('Значения по квадратам, слева направо', patch.values));
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
      xCount: h('input', {type: 'number', min: '2', max: '7', step: '1', value: 5}),
      yCount: h('input', {type: 'number', min: '2', max: '7', step: '1', value: 5}),
      geometry: h('select', {}, [h('option', {value: 'line'}, 'Векторная линия'), h('option', {value: 'fill'}, 'Залитый участок'),
        h('option', {value: 'text'}, 'Заполненные буквы A8M трёх размеров'),
        h('option', {value: 'vector_text'}, 'Векторные буквы A8M B012 · 2/4 мм × 2')]),
      wobbleStep: h('input', {type: 'number', min: '0.001', max: '1', step: 'any', value: '0.02'}),
    };
    const matrixAxes = Object.entries(MATRIX_AXES).map(([key, value]) => h('option', {value: key}, value.name));
    matrix.xAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.yAxis.replaceChildren(...matrixAxes.map((o) => o.cloneNode(true)));
    matrix.xAxis.value = 'power'; matrix.yAxis.value = 'speed';
    const matrixCard = h('div', {class: 'card stack', style: 'display:none'},
      h('p', {class: 'muted small'}, 'Как в LightBurn Material Test: две выбранные оси меняются по сетке, остальные параметры остаются постоянными. До 28 ячеек; с чисткой и регистрацией получится не более 30 выходных слоёв.'),
      h('div', {class: 'grid g3'}, field('Ось X', matrix.xAxis), field('Ось Y', matrix.yAxis), field('Геометрия ячейки', matrix.geometry)),
      h('div', {class: 'grid g3'}, field('X: от', matrix.xMin), field('X: до', matrix.xMax), field('Точек по X', matrix.xCount)),
      h('div', {class: 'grid g3'}, field('Y: от', matrix.yMin), field('Y: до', matrix.yMax), field('Точек по Y', matrix.yCount)),
      field('Шаг wobble, мм (при включении)', matrix.wobbleStep),
      h('p', {class: 'muted small'}, 'Для Q-Pulse используются только ступени из паспорта лазера. Шаг линий действует только для заливки и заполненных букв. Wobble проверяется на векторных линиях и однолинейных буквах.'));
    const settings = {
      power: h('input', {type: 'number', min: '1', max: '100', step: 'any', value: DEFAULTS.power}),
      frequency: h('input', {type: 'number', min: '1', step: 'any', value: DEFAULTS.frequency}),
      speed: h('input', {type: 'number', min: '1', max: '10000', step: 'any', value: DEFAULTS.speed}),
      pulse: h('select', {'aria-label': 'Длительность импульса'}),
      interval: h('input', {type: 'number', min: '0.001', max: '1', step: 'any', value: DEFAULTS.line_interval}),
      passes: h('input', {type: 'number', min: '1', max: '20', step: '1', value: DEFAULTS.passes}),
      global: h('input', {type: 'number', min: '1', max: '20', step: '1', value: DEFAULTS.global_passes}),
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
      if (resetSize) maxWidth.value = maxHeight.value = type.value === 'small_patches' ? '25' : '100';
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
    device.addEventListener('change', () => { fillHardware(); changeDescription(); });
    type.addEventListener('change', () => changeDescription(true));
    matrix.xAxis.addEventListener('change', () => updateMatrixAxes('xAxis'));
    matrix.yAxis.addEventListener('change', () => updateMatrixAxes('yAxis'));
    patch.count.addEventListener('change', patchDefaults);
    patch.axis.addEventListener('change', patchDefaults);
    fillHardware(); changeDescription();

    const newMaterial = {
      name: h('input', {placeholder: 'Например: лист Grade 2'}),
      family: h('input', {value: 'Titanium', placeholder: 'Titanium, Steel, Brass…'}),
      grade: h('input', {placeholder: 'Grade 2, Ti-6Al-4V…'}),
      batch: h('input', {placeholder: 'номер партии или листа'}),
    };
    const addMaterial = async () => {
      try {
        const saved = await post('/materials', {name: newMaterial.name.value.trim(), family: newMaterial.family.value.trim(), grade: newMaterial.grade.value.trim() || null,
          batch: newMaterial.batch.value.trim() || null, thickness_mm: null, surface: null});
        materials.push(saved);
        material.append(h('option', {value: saved.id, selected: true}, materialName(saved)));
        material.value = saved.id;
        newMaterial.name.value = newMaterial.grade.value = newMaterial.batch.value = '';
        toast('Заготовка сохранена и выбрана', 'ok');
      } catch (e) { fail(e); }
    };

    const body = h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'Выбери тест, лазер и заготовку. Рецепт предварительной очистки пока задан для титана.'),
      field('Тип экспериментальной платы', type), desc,
      field('Лазер', device), hardware,
      field('Заготовка', material),
      h('div', {class: 'grid g2'}, field('Максимальная ширина платы, мм', maxWidth),
        field('Максимальная высота платы, мм', maxHeight)),
      matrixCard, smallCard,
      h('details', {class: 'card'}, h('summary', {}, 'Добавить новую заготовку'),
        h('div', {class: 'stack', style: 'margin-top:12px'},
          h('div', {class: 'grid g3'}, field('Материал', newMaterial.family), field('Название / лист', newMaterial.name), field('Марка / сплав', newMaterial.grade), field('Партия', newMaterial.batch)),
          btn('Сохранить заготовку', addMaterial))),
      h('details', {class: 'card'}, h('summary', {}, 'Основные параметры опыта'),
        h('p', {class: 'muted small'}, 'Эти значения — настройки этой платы и сохраняются с ней. Тип платы сам перебирает указанные в описании оси; поля задают остальные условия. Для матрицы выбранные оси переопределяют соответствующие базовые значения. Для частотного теста выбирается CW-ступень, если она указана в паспорте.'),
        h('div', {class: 'grid g3'}, field('Базовая мощность, %', settings.power), field('Базовая частота, кГц', settings.frequency), field('Базовая скорость, мм/с', settings.speed),
          field('Q-Pulse, нс', settings.pulse), field('Интервал линий, мм', settings.interval), field('Проходы слоя', settings.passes),
          field('Глобальные проходы', settings.global))),
      h('details', {class: 'card'}, h('summary', {}, 'Параметры очистки и меток'),
        h('p', {class: 'muted small'}, 'В каждом LightBurn-файле первым будет слой чистки: 20% / 48 кГц / 2000 мм/с, Q-Pulse 200 нс, шаг 0,05 мм, один проход слоя и один глобальный проход, двунаправленно и cross-hatch. Затем идут чёрные подписи/метки и тестовые слои. Для выбранного лазера чистка автоматически подстраивается только если паспорт не поддерживает 48 кГц или 200 нс.')));

    const requestBody = () => {
      const laser = available.find((d) => String(d.id) === device.value);
      if (!laser) throw new Error('Выбери лазер с установленной линзой');
      if (!type.value) throw new Error('Выбери тип экспериментальной платы');
      if (!material.value) throw new Error('Выбери или добавь конкретную заготовку');
      if (settings.pulse.value === '') throw new Error('Выбери длительность импульса Q-Pulse из ступеней лазера');
      const out = {device_id: +laser.id, material_id: +material.value, test_type: type.value,
        power: +settings.power.value, frequency: +settings.frequency.value, speed: +settings.speed.value,
        pulse_width: +settings.pulse.value, line_interval: +settings.interval.value,
        passes: +settings.passes.value, global_passes: +settings.global.value,
        max_width_mm: +maxWidth.value, max_height_mm: +maxHeight.value,
        split_if_needed: true,
        matrix: {x_axis: matrix.xAxis.value, y_axis: matrix.yAxis.value, geometry: matrix.geometry.value,
          wobble_step: +matrix.wobbleStep.value,
          x_min: +matrix.xMin.value, x_max: +matrix.xMax.value, x_count: +matrix.xCount.value,
          y_min: +matrix.yMin.value, y_max: +matrix.yMax.value, y_count: +matrix.yCount.value}};
      if (type.value === 'small_patches') {
        const count = +patch.count.value;
        const numbers = patch.values.value.split(/[,;\s]+/).filter(Boolean).map(Number);
        if (count > 1 && (numbers.length !== count || numbers.some((n) => !Number.isFinite(n)))) {
          throw new Error(`Для ${count} квадратов укажите ровно ${count} числовых значения`);
        }
        out.patch_size_mm = +patch.size.value;
        out.registration = patch.registration.value;
        out.patches = count === 1 ? [{}] : numbers.map((value) => ({[patch.axis.value]: value}));
      }
      return out;
    };
    smallCard.append(btn('Показать размер', async () => {
      try {
        const result = await post('/capability-plates/preview', requestBody());
        const parts = result.parts || [{summary: result.summary, output_layers: result.output_layers}];
        previewText.replaceChildren(...parts.map((part, index) => {
          const size = part.summary.size_mm;
          return h('div', {}, `Часть ${index + 1}/${parts.length}: ${size.width} × ${size.height} мм · `,
            `${part.summary.registration === 'full' ? 'QR и метки' : 'без меток'} · `,
            `${part.summary.test_features} квадрат(а) · ${part.output_layers} выходных слоя · `,
            `очистка ${part.summary.clean_area_mm2} мм²`);
        }));
      } catch (e) { fail(e); }
    }));

    return modal('Создать экспериментальную плату', body, [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Создать плату', cls: 'primary', run: async (x) => {
        const made = await post('/capability-plates', requestBody());
        x.close();
        if (reload) reload();
        const parts = made.parts || [made];
        if (parts.length === 1) {
          toast(`Создано: ${parts[0].name} · ${parts[0].summary.layers} тестовых слоёв`, 'ok');
          go('/experiment/plan-' + parts[0].plan_id);
        } else {
          modal('Части компактного теста', h('div', {class: 'stack'},
            h('p', {}, `Создано ${parts.length} самостоятельных LightBurn-файла. Каждый начинается с локальной чистки${parts[0].summary.registration === 'full' ? ' и имеет собственные метки' : ''}.`),
            ...parts.map((part, index) => h('div', {class: 'card row'},
              h('strong', {}, `Часть ${index + 1}/${parts.length} · квадраты ${part.sample_indexes.join(', ')}`),
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
