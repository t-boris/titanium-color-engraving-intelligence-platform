/* Вкладки «Правила оценки» для лазера с линзой и «Слой маркеров» (REQ-005, DEC-021, DEC-027, DEC-063). */
'use strict';
const SetupRules = (() => {
  const {h, btn, field, link, get, put, toast} = App;

  async function rulesTab(ctx, reload) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => reload('rules', pick.route())});
    const r = await get('/rules?' + pick.query());
    // the three thresholds are read as setup.save_rules reads them (a whole number from 1; two numbers that are not negative); an empty box stays unset,
    // a wrong one is said beside it and kept, and a refusal of the server stands above the button (ux-save-feedback-p0, REQ-003)
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const repField = form.add('repeat_threshold', 'Сколько гравировок повторить', Forms.numberInput(Q.repeatThreshold, {value: r.repeat_threshold ?? ''}), {quantity: 'repeatThreshold'});
    const tolField = form.add('delta_tolerance', 'Допуск цветового отклонения', Forms.numberInput(Q.deltaTolerance, {value: r.delta_tolerance ?? ''}), {quantity: 'deltaTolerance'});
    const varField = form.add('variance_threshold', 'Допустимая дисперсия цвета', Forms.numberInput(Q.varianceThreshold, {value: r.variance_threshold ?? ''}), {quantity: 'varianceThreshold'});
    const agreed = h('input', {type: 'checkbox', checked: r.criteria_agreed});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Как система оценивает повторяемость'),
      h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Лазер', pick.laser)), h('div', {class: 'f-wrap'}, field('Линза', pick.lens))),
      h('p', {class: 'muted small'}, 'Правила задаются для каждого лазера с линзой отдельно. Работы с неизвестной линзой оцениваются по своим правилам и с другими не смешиваются.'),
      r.criteria_agreed
        ? h('div', {class: 'alert ok'}, 'Автоматическое повышение до «Валидировано» включено по указанным ниже критериям.')
        : h('div', {class: 'alert warn'}, 'Пока критерии не согласованы, записи остаются измеренными/повторёнными и не повышаются автоматически.'),
      h('p', {class: 'muted'}, 'Эти правила нужны только для автоматической отметки надёжности результата. Они не меняют параметры лазера, файл LightBurn или сам цвет.'),
      h('ul', {class: 'muted small'},
        h('li', {}, 'Независимые повторы — отдельные физические гравировки одного набора параметров; пересъёмка той же гравировки не считается.'),
        h('li', {}, 'Допуск ΔE — максимальное цветовое отклонение между повторами, которое вы считаете приемлемым.'),
        h('li', {}, 'Порог дисперсии — дополнительная граница разброса цвета между повторами; меньше означает стабильнее.')),
      h('div', {class: 'grid g3'}, repField, tolField, varField),
      h('p', {class: 'muted small'}, 'При заполнении всех трёх значений система сможет отметить результат «Валидировано», когда наберётся нужное число независимых гравировок и оба показателя разброса окажутся в пределах порогов. Значения выбираете вы; заранее заданных нет.'),
      h('label', {class: 'row'}, agreed, h('span', {}, 'Включить автоматическую оценку по этим критериям')),
      form.error,
      h('div', {class: 'row'}, btn('Сохранить пороги', async () => {
        const v = form.collect();
        if (!v) return;
        try {
          await put('/rules', {device_id: pick.deviceId(), lens_id: pick.lensId(), ...v, criteria_agreed: agreed.checked});
          toast('Пороги сохранены', 'ok'); reload('rules', pick.route());
        } catch (e) { form.fail(e); }
      }, 'primary'), link('/colors?' + pick.route(), 'Модель цвета этого лазера с линзой')));
  }

  async function markersTab(reload) {
    const cur = await get('/marker-layer');
    // plans.save_marker_layer_settings: power, frequency and speed must be above 0 (and are required); the other three may stay empty (LightBurn then
    // takes its own value) and are above 0 when set, the passes a whole number from 1. The laser's own power and frequency range is judged
    // when a plate is made with them, not here (ux-save-feedback-p0, REQ-003)
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const box = (quantity, value) => Forms.numberInput(Q[quantity], {value: value ?? ''});
    const power = form.add('power', 'Мощность', box('markerPower', cur?.power), {quantity: 'markerPower', required: true});
    const frequency = form.add('frequency', 'Частота', box('markerFrequency', cur?.frequency), {quantity: 'markerFrequency', required: true});
    const speed = form.add('speed', 'Скорость', box('markerSpeed', cur?.speed), {quantity: 'markerSpeed', required: true});
    const pulse = form.add('pulse_width', 'Q-Pulse (необязательно)', box('markerPulse', cur?.pulse_width), {quantity: 'markerPulse'});
    const interval = form.add('line_interval', 'Интервал линий (необязательно)', box('markerInterval', cur?.interval), {quantity: 'markerInterval'});
    const passes = form.add('passes', 'Проходов (необязательно)', box('markerPasses', cur?.passes), {quantity: 'markerPasses'});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Кодовые метки на тестовой плате'),
      h('p', {class: 'muted'}, 'Это не тестовый рисунок и не слой чистки. Вокруг матрицы идут четыре угловые метки и QR с номером эксперимента. Они помогают программе выровнять фотографию и понять, какая пластина снята. В измерения цвета они не входят.'),
      h('p', {class: 'muted small'}, 'В LightBurn эти фигуры находятся на отдельном слое «Markers» (на платах проверки лазера — «Markers and labels», вместе с выгравированными подписями), поэтому при желании его можно выключить. '
        + 'Параметры ниже задают, как метки и подписи прожигаются на титане; этот слой идёт после обязательной чистки и до тестовых ячеек. Пока они не заданы, платы с метками не создаются.'),
      h('p', {class: 'muted small'}, 'Метки, подписи и чистка сохраняются как свидетельство и видны на снимке, но никогда не попадают в модель цвета и в знание.'),
      cur ? null : h('div', {class: 'alert warn'}, 'Параметры кодовых меток пока не заданы. Их нужно задать один раз и проверить на титане перед автоматическим поиском меток по фотографии.'),
      h('div', {class: 'grid g3'}, power, frequency, speed),
      h('div', {class: 'grid g3'}, pulse, interval, passes),
      h('p', {class: 'muted small'}, 'Незаданный параметр не подставляется: LightBurn возьмёт своё значение по умолчанию.'),
      form.error,
      btn('Сохранить параметры кодовых меток', async () => {
        const v = form.collect();
        if (!v) return;
        try {
          await put('/marker-layer', v);
          toast('Слой маркеров сохранён', 'ok'); reload('markers');
        } catch (e) { form.fail(e); }
      }, 'primary'));
  }

  return {rulesTab, markersTab};
})();
