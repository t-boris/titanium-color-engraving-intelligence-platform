/* Лазер и линза работы (DEC-042, DEC-063): лазер — физический прибор, линза — её запись, «неизвестна» — отдельный выбор.
   Знания разных лазеров и линз, в том числе неизвестной, не смешиваются. Адрес экрана: ?device=<id>&lens=<id|unknown>;
   сервер принимает lens_id=unknown в запросах и формах и null в JSON. */
'use strict';
Object.assign(App, (() => {
  const {h, get} = App;
  const UNKNOWN = 'unknown';

  /** Название линзы с фокусом, когда он известен; линза без фокусного расстояния остаётся неполной (REQ-019). */
  function lensLabel(lens) {
    if (!lens) return 'линза неизвестна';
    return lens.focal_length_mm == null ? `${lens.name} · фокус неизвестен` : `${lens.name} · ${+lens.focal_length_mm} мм`;
  }

  /** Линза для JSON: номер записи или null — линза неизвестна. */
  const lensBody = (value) => (value == null || value === '' || value === UNKNOWN ? null : +value);
  /** Линза для адреса или формы: номер записи или unknown. */
  const lensParam = (value) => (value == null || value === '' || value === UNKNOWN ? UNKNOWN : String(value));

  /** Лазеры и линзы для выбора. */
  async function hardwareLists() {
    const [devices, lenses] = await Promise.all([get('/devices'), get('/lenses')]);
    return {devices, lenses};
  }

  /** Два списка: лазер и линза. Линза — любая запись линзы или «неизвестна»; установленная на выбранном лазере помечена.
      По умолчанию (defaultLens) — 'installed': линза, стоящая на лазере сейчас, или 'unknown': импортированная работа
      не получает установленную линзу без выбора оператора (REQ-016). onChange вызывается при смене лазера или линзы. */
  function laserLensPicker({devices, lenses}, {device = null, lens = null, defaultLens = 'installed', onChange = null} = {}) {
    const laserSelect = h('select', {'aria-label': 'Лазер'}, devices.map((d) => h('option', {value: d.id}, d.title || d.name)));
    if (device != null && devices.some((d) => String(d.id) === String(device))) laserSelect.value = String(device);
    const lensSelect = h('select', {'aria-label': 'Линза'});
    const current = () => devices.find((d) => String(d.id) === laserSelect.value) || null;
    const fillLenses = (wanted) => {
      const installed = current()?.lens?.id ?? null;
      lensSelect.replaceChildren(h('option', {value: UNKNOWN}, 'неизвестна'),
        ...lenses.map((l) => h('option', {value: l.id}, lensLabel(l) + (l.id === installed ? ' (установлена)' : ''))));
      const fallback = defaultLens === 'installed' && installed != null ? String(installed) : UNKNOWN;
      const asked = wanted == null ? null : lensParam(wanted);
      lensSelect.value = asked != null && [...lensSelect.options].some((o) => String(o.value) === asked) ? asked : fallback;
    };
    fillLenses(lens);
    laserSelect.addEventListener('change', () => { fillLenses(null); if (onChange) onChange(); });
    lensSelect.addEventListener('change', () => { if (onChange) onChange(); });
    return {
      laser: laserSelect, lens: lensSelect, device: current,
      deviceId: () => +laserSelect.value, lensId: () => lensBody(lensSelect.value), lensValue: () => lensSelect.value,
      setLens: (id) => { lensSelect.value = lensParam(id); },
      query: () => `device_id=${laserSelect.value}&lens_id=${lensSelect.value}`,     // для запросов к серверу
      route: () => `device=${laserSelect.value}&lens=${lensSelect.value}`,           // для адреса экрана
    };
  }

  /** Лазер и линза из адреса экрана в виде запроса к серверу. */
  const hardwareQuery = (device, lens) => `device_id=${device}&lens_id=${lensParam(lens)}`;

  return {lensLabel, lensBody, lensParam, hardwareLists, laserLensPicker, hardwareQuery};
})());
