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
      /** Choose a laser and its lens from outside (the shared context changed): the lens list is made again for that laser; no ``onChange`` call. */
      setDevice: (id, lens = null) => { if (devices.some((d) => String(d.id) === String(id))) { laserSelect.value = String(id); fillLenses(lens); } },
      query: () => `device_id=${laserSelect.value}&lens_id=${lensSelect.value}`,     // для запросов к серверу
      route: () => `device=${laserSelect.value}&lens=${lensSelect.value}`,           // для адреса экрана
    };
  }

  /** Лазер и линза из адреса экрана в виде запроса к серверу. */
  const hardwareQuery = (device, lens) => `device_id=${device}&lens_id=${lensParam(lens)}`;

  /** С чего начинается новая работа или новый тест (ux-work-creation-p0, REQ-001): лазер, линза и заготовка из адреса экрана, а без них — из общего
      контекста мастерской (последний явный выбор). Адрес сильнее общего выбора: ссылка, сделанная для одной установки, открывается на ней; лазер из
      адреса без линзы берёт линзу, стоящую на нём, а не линзу общего выбора для другого лазера. Не прочитанный контекст — не отказ формы: всё
      остаётся, как было до него. Ответ: {device, lens, material, source, context}; lens — номер записи, 'unknown' или null (линза, стоящая на лазере). */
  async function contextStart(query = {}) {
    let c = null;
    try { c = await App.get('/creation/context'); } catch (_) { c = null; }
    const fromAddress = query.device != null && query.device !== '';
    const lens = fromAddress ? query.lens ?? null : c && c.device_id != null ? (c.lens_id == null ? UNKNOWN : c.lens_id) : null;
    return {device: fromAddress ? query.device : c ? c.device_id : null, lens, material: c ? c.material_id : null, source: c ? c.source : null, context: c};
  }

  /** Запомнить установку, с которой сделана работа, как общий контекст следующей новой работы. ``source``: не передан — не менять, null — свои
      измерения, объект — выпуск лаборатории (``label`` — как его видел оператор). Отказ ничего не сообщает: работа уже сделана. */
  async function rememberContext({device, lens, material, source, label} = {}) {
    const body = {device_id: +device, lens_id: lensBody(lens)};
    if (material != null && material !== '') body.material_id = +material;          // a form that has no titanium leaves the shared one as it is
    if (source !== undefined) body.source = source ? {...source, label: label || null} : null;
    try { return await App.put('/creation/context', body); } catch (_) { return null; }
  }

  /** The measured scale of the context's own laser, lens and titanium (the best first), as the mode a photo work is made on; null when it has none.
      A work made without naming one would take the best scale of the whole workshop, whatever laser it was measured with. */
  async function contextScale(context, widthMm) {
    const {scales} = await App.get(`/grey-scales?device_id=${context.device_id}&lens_id=${lensParam(context.lens_id)}&material_id=${context.material_id}&row_mm=${widthMm}`);
    const own = (scales || []).find((sc) => sc.mode.device_id === context.device_id && sc.mode.lens_id === context.lens_id && sc.mode.material_id === context.material_id);
    return own ? own.mode : null;
  }

  /** One line with the context an opened photo work was made with: the laser and lens of its scale, its titanium and where its measurements come from
      (ux-work-creation-p0, REQ-001). It is the work's own, as saved in it; the shared choice of the workshop never changes it. Empty when the lists cannot be read. */
  async function workContextText(work) {
    let lists = null;
    try { lists = await hardwareLists(); } catch (_) { return ''; }
    const scale = work.scale || {};
    const device = lists.devices.find((d) => d.id === scale.device_id), lens = lists.lenses.find((l) => l.id === scale.lens_id);
    const stock = work.material ? [work.material.name, work.material.grade, work.material.batch && `партия ${work.material.batch}`].filter(Boolean).join(' · ') : null;
    const s = work.source;
    return [`Лазер: ${device ? device.title || device.name : 'не найден'}`, `линза: ${lens ? lensLabel(lens) : 'неизвестна'}`, `титан: ${stock || 'не указан'}`,
      `измерения: ${s && s.kind === 'release' ? 'лаборатория ' + s.lab_name : 'этой мастерской'}`].join(' · ');
  }

  /** An older form that cannot make ``result`` from the shared context hands over to the creation screen, which says what is missing and offers the
      starter test, instead of letting the server refuse once the person has chosen a picture. True when it handed over; a failure to ask is no refusal. */
  async function handOverToCreation(result) {
    let ready;
    try { ready = await App.get(`/creation/readiness?result=${result}`); } catch (_) { return false; }
    if (!ready || ready.ready !== false) return false;
    App.go(`/new?result=${result}`);
    return true;
  }

  return {lensLabel, lensBody, lensParam, hardwareLists, laserLensPicker, hardwareQuery, contextStart, rememberContext, contextScale, workContextText, handOverToCreation};
})());
