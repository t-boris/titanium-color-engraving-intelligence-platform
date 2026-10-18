/* «Что это за лазер»: вывод из введённых данных, то есть то, что видят расчёты (REQ-018, DEC-040).
   Для каждой величины показано, откуда она взята и участвует ли в расчётах. Считает сервер, здесь только слова. */
'use strict';
const DeviceCharacterCard = (() => {
  const {h, pill, link, facts} = App;
  const g = (v, d = 4) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const STATE = {used: ['участвует в расчётах', 'ok'], waiting: ['ждёт подтверждения', 'warn'], reference: ['справочно', ''], unknown: ['не задано', 'bad']};
  const BASIS = {installed: 'установлена вами', bound: 'только границы (нужно M²)', lens: 'поле линзы', 'lens and laser settings': 'меньшее из линзы и настроек',
    measured: 'измерено вами / на экземпляре', rated: 'номинал из паспорта', controller: 'сужено настройками контроллера', laser: 'паспорт лазера',
    passport: 'паспорт', calculated: 'рассчитано', nominal: 'номинал'};
  const WAIT = {'Min PWM': 'Min PWM', 'Max PWM': 'Max PWM', 'Field Size': 'Field Size', 'Size Width': 'Size Width', 'Size Height': 'Size Height',
    lens: 'линза', focal_length: 'фокусное расстояние линзы', beam_diameter: 'диаметр пучка', wavelength: 'длина волны', m2: 'M²'};

  function label(i) {
    const v = i.value;
    switch (i.key) {
      case 'power': return ['Мощность лазера', `${g(v, 4)} Вт`, 'От неё считаются мощность на выходе и энергия импульса.'];
      case 'frequency_range': return ['Рабочие частоты', `${g(v.min)}–${g(v.max)} кГц`, 'Выход за них не блокируется, но в расчёте появляется предупреждение.'];
      case 'work_field': return ['Рабочее поле', v ? `${g(v.width)} × ${g(v.height)} мм` : '—', 'Плата с маркерами больше поля не создаётся.'];
      case 'pulse_widths': return ['Длительности импульса', `${v.length} ступеней`, 'Платы и планы принимают только их.'];
      case 'max_pulse_energy': return ['Наибольшая энергия импульса', v == null ? '—' : `${g(v)} мДж`, 'Расчётная энергия выше этого значения не поднимается.'];
      case 'spot_diameter': return ['Диаметр пятна', v != null ? `${g(v, 3)} мкм` : (i.low ? `${g(i.low, 3)}${i.high ? '–' + g(i.high, 3) : '+'} мкм` : '—'), 'Нужен для плотности энергии и перекрытия импульсов; считается по линзе.'];
      case 'lens': return ['Линза', v ? App.lensLabel(v) : 'не установлена', 'Задаёт пятно и поле; при замене новые платы запоминают новую.'];

      case 'wavelength': return ['Длина волны', v == null ? '—' : `${g(v)} нм`, 'Справка: на расчёты не влияет.'];
      default: return ['Пиковая мощность в импульсе', v == null ? '—' : `${g(v)} кВт`, 'Справка: по форме импульса из протокола.'];
    }
  }

  function card(d) {
    const rows = d.characterization.items.map((i) => {
      const [name, value, why] = label(i), [state, kind] = STATE[i.state];
      return [h('div', {}, h('strong', {}, name), h('div', {class: 'small muted'}, why)), h('strong', {}, value), BASIS[i.basis] || i.basis || '—',
        h('span', {}, pill(state, kind), i.waiting_for.length ? h('div', {class: 'small muted'}, 'ждёт: ' + i.waiting_for.map((k) => WAIT[k] || k).join(', ')) : null)];
    });
    const waiting = d.characterization.items.filter((i) => i.state === 'waiting' || i.waiting_for.length);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Что это за лазер'),
      h('p', {class: 'muted small'}, 'Вывод из того, что введено в паспорте, протоколе, формах импульса и настройках. Считается заново при каждом открытии: подтвердили или исправили значение, и вывод изменился. '
        + 'Значение от руки, которое вы не подтвердили, в расчётах не участвует.'),
      App.table(['Что', 'Значение', 'На чём основано', 'Расчёты'], rows, undefined, true),
      waiting.length ? h('div', {class: 'alert warn'}, 'Чтобы эти значения начали работать, подтвердите их ✓ на вкладке ', link(`/devices/${d.id}?tab=controller`, 'Настройки лазера'), '.') : null);
  }
  return {card};
})();
