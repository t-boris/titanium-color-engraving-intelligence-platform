/* Надписи в работах (feature inscriptions-in-works, REQ-001..REQ-005, DEC-001..DEC-004): вкладка «Надписи» векторной работы и работы
   фотогравировки, окно шрифтов и слой надписей поверх картинки работы.
   Надпись — объект работы: текст, шрифт, высота букв, ширина, интервалы, расположение (прямо, дугой, по кругу, по пути), поворот, место,
   цвет титана, зазор и подложка. Сервер раскладывает её сам и присылает контуры букв, подложки и врезки в мм работы; экран их рисует и
   двигает: перетаскивание надписи — место, круглая ручка — поворот, квадратная — размер, точки пути — сам путь. Каждое изменение — одна
   операция работы (text_add, text_set, text_copy, text_delete) и один шаг отмены. В векторной работе слой рисует врезку цветом чистого
   титана, подложку и буквы их цветами (области под ними на картинке целые: врезает их файл); в фотогравировке это уже нарисовано на
   прогнозе сервером, слой даёт только ручки и контур при перетаскивании.
   Окно шрифтов: шрифты этого Mac, свои файлы (TTF, OTF, TTC) и Google Fonts — поиск, письменность, вид, избранные, у каждого семейства
   его начертания и образец текста надписи этим шрифтом; семейство Google скачивается, когда оно видно в списке (до 2 МБ) или по кнопке. */
'use strict';
const Lettering = (() => {
  const {h, fill, btn, get, post, form, del, toast, num, labText, modal, confirmBox, fail} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const LAYOUTS = [['line', 'Прямо'], ['arc', 'Дугой'], ['circle', 'По кругу'], ['path', 'По пути']];
  const ALIGNS = [['left', 'Слева'], ['center', 'По центру'], ['right', 'Справа']];
  const LETTERS = [['upright', 'Стоят прямо'], ['bent', 'Гнутся по кривой']];
  const BACKINGS = [['none', 'Без подложки'], ['rect', 'Прямоугольник'], ['oval', 'Овал'], ['outline', 'По контуру букв']];
  const SCRIPTS = {latin: 'Латиница', cyrillic: 'Кириллица', greek: 'Греческий', hebrew: 'Иврит', arabic: 'Арабский', armenian: 'Армянский',
    georgian: 'Грузинский', devanagari: 'Деванагари', thai: 'Тайский', japanese: 'Японский', korean: 'Корейский', chinese: 'Китайский'};
  const KINDS = {serif: 'С засечками', sans: 'Без засечек', handwriting: 'Рукописные', display: 'Декоративные', monospace: 'Моноширинные',
    symbol: 'Символы', other: 'Другие'};
  const SOURCES = {mac: 'Этого Mac', own: 'Свои', google: 'Google Fonts'};
  const SAMPLE = 'Надпись Abc';
  // the letters of a script other than Latin, to open the font window on the fonts that write the inscription (fonts.SCRIPTS)
  const LETTERS_OF = [['cyrillic', /[\u0400-\u04ff]/], ['greek', /[\u0370-\u03ff]/], ['hebrew', /[\u0590-\u05ff]/], ['arabic', /[\u0600-\u06ff]/],
    ['armenian', /[\u0530-\u058f]/], ['georgian', /[\u10a0-\u10ff]/], ['devanagari', /[\u0900-\u097f]/], ['thai', /[\u0e00-\u0e7f]/],
    ['japanese', /[\u3040-\u30ff]/], ['korean', /[\uac00-\ud7af]/], ['chinese', /[\u4e00-\u9fff]/]];
  const scriptOf = (text) => (LETTERS_OF.find(([, re]) => re.test(text || '')) || [''])[0];
  const PAGE = 60;                            // семейств в окне шрифтов за раз
  const AUTO_BYTES = 2 * 1024 * 1024;         // семейство Google не больше этого скачивается само, когда видно в списке
  const TYPE_MS = 700;                        // текст надписи уходит на сервер, когда его перестали набирать на столько
  const HANDLE_PX = 7;                        // радиус ручек на экране
  const MAX_POINTS = 400;                     // the most points of a path the server takes (lettering.MAX_POINTS)
  // A path drawn freehand keeps no wiggle smaller than STROKE_PX on screen (the hand's tremor and the pointer's step, which the operator
  // cannot place on purpose) or than a tenth of the letters' height (the server lays the letters on a smooth curve through the points:
  // a bump that small in their baseline does not change how they stand). The tolerance doubles until the stroke fits MAX_POINTS.
  const STROKE_PX = 2;
  const STROKE_OF_HEIGHT = 0.1;
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  /** The points of a polyline that keep it within ``tol`` of every point dropped (Douglas–Peucker, by the distance to the segment between
      the points kept): the first and the last always stay. */
  function simplify(pts, tol) {
    if (pts.length < 3) return pts.slice();
    const keep = new Uint8Array(pts.length);
    keep[0] = keep[pts.length - 1] = 1;
    const stack = [[0, pts.length - 1]];
    while (stack.length) {
      const [a, b] = stack.pop();
      const [ax, ay] = pts[a], dx = pts[b][0] - ax, dy = pts[b][1] - ay, len2 = dx * dx + dy * dy;
      let far = -1, worst = tol;
      for (let i = a + 1; i < b; i++) {
        const px = pts[i][0] - ax, py = pts[i][1] - ay, k = len2 ? clamp((px * dx + py * dy) / len2, 0, 1) : 0;
        const d = Math.hypot(px - k * dx, py - k * dy);
        if (d > worst) { worst = d; far = i; }
      }
      if (far >= 0) { keep[far] = 1; stack.push([a, far], [far, b]); }
    }
    return pts.filter((_, i) => keep[i]);
  }
  const svgEl = (tag, attrs = {}) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
    return el;
  };
  const turn = ([x, y], deg) => {                       // по часовой стрелке при y вниз, как на сервере
    const a = deg * Math.PI / 180;
    return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)];
  };
  const short = (text) => {
    const line = String(text || '').split('\n')[0];
    return line.length > 28 ? line.slice(0, 27) + '…' : line || '(пусто)';
  };
  const storage = {
    read(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; } },
    write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* без хранилища не запоминается */ } },
  };

  // --- окно шрифтов -----------------------------------------------------------------------------------------------------------
  /** Окно шрифтов: ``current`` — шрифт надписи ({face, family, style}), ``sample`` — её текст; ``onPick(font)`` — выбранный. */
  async function fontWindow(current, sample, onPick) {
    let catalogue;
    try { catalogue = await get('/fonts'); } catch (e) { return fail(e); }
    const favourites = new Set(storage.read('lt.fav') || []);
    let chosen = current ? {family: current.family, face: current.face} : null, shownCount = PAGE, polling = null;
    const queue = [], loading = new Set();
    const text = h('input', {type: 'text', value: (sample || '').split('\n').join(' ').slice(0, 60) || SAMPLE, 'aria-label': 'Образец текста'});
    const search = h('input', {type: 'search', placeholder: 'Название шрифта', 'aria-label': 'Найти шрифт по названию'});
    const option = (value, label) => h('option', {value}, label);
    const source = h('select', {'aria-label': 'Откуда шрифты'}, option('', 'Все шрифты'), Object.entries(SOURCES).map(([k, v]) => option(k, v)),
      option('fav', 'Избранные'));
    const script = h('select', {'aria-label': 'Письменность'}, option('', 'Любая письменность'), Object.entries(SCRIPTS).map(([k, v]) => option(k, v)));
    const kind = h('select', {'aria-label': 'Вид шрифта'}, option('', 'Любой вид'), Object.entries(KINDS).map(([k, v]) => option(k, v)));
    script.value = scriptOf(sample);              // the fonts that write the inscription's own letters first; «Любая письменность» shows all
    const list = h('div', {class: 'lt-fonts', role: 'listbox', 'aria-label': 'Шрифты'});
    const more = h('div', {});
    const count = h('p', {class: 'small muted'});
    const googleBox = h('div', {class: 'stack small'});
    const ownInput = h('input', {type: 'file', accept: '.ttf,.otf,.ttc', 'aria-label': 'Свой файл шрифта (TTF, OTF, TTC)'});
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver((seen) => {
      for (const e of seen) if (e.isIntersecting) { observer.unobserve(e.target); want(e.target.getAttribute('data-family')); }
    }, {root: null, rootMargin: '200px'});

    const sampleText = () => text.value.trim() || SAMPLE;
    const preview = (faceId) => `/api/fonts/preview.svg?face=${encodeURIComponent(faceId)}&text=${encodeURIComponent(sampleText())}&height=10`;
    const families = () => catalogue.families.filter((f) => {
      if (source.value === 'fav' ? !favourites.has(f.family) : source.value && f.source !== source.value) return false;
      if (script.value && !f.scripts.includes(script.value)) return false;
      if (kind.value && f.kind !== kind.value) return false;
      const q = search.value.trim().toLowerCase();
      return !q || f.family.toLowerCase().includes(q);
    });

    /** Семейство Google, которое видно в списке, скачивается само (небольшое, по два за раз); большое — кнопкой. */
    function want(family) {
      const f = catalogue.families.find((x) => x.family === family && x.source === 'google' && !x.downloaded);
      if (!f || f.size > AUTO_BYTES || loading.has(family) || queue.includes(family)) return;
      queue.push(family);
      pump();
    }
    function pump() {
      while (loading.size < 2 && queue.length) {
        const family = queue.shift();
        loading.add(family);
        download(family).finally(() => { loading.delete(family); pump(); });
      }
    }
    async function download(family) {
      try {
        const got = await post('/fonts/google/family', {family});
        const f = catalogue.families.find((x) => x.family === family && x.source === 'google');
        // Google names a family's upright normal face «Regular»; the catalogue gives it as ``regular`` (fonts._regular)
        if (f) Object.assign(f, {downloaded: true, faces: got.faces.map((x) => ({id: x.face, style: x.style})),
          regular: (got.faces.find((x) => x.style === 'Regular') || got.faces[0]).face});
      } catch (e) { toast(e.message, 'bad'); }
      render(false);
    }

    function row(f) {
      const on = chosen && chosen.family === f.family;
      const star = h('button', {type: 'button', class: 'lt-star', 'aria-pressed': favourites.has(f.family) ? 'true' : 'false',
        title: favourites.has(f.family) ? 'Убрать из избранных' : 'В избранные', 'aria-label': `${f.family}: избранный`,
        onClick: (ev) => { ev.stopPropagation(); if (favourites.has(f.family)) favourites.delete(f.family); else favourites.add(f.family);
          storage.write('lt.fav', [...favourites]); render(false); }}, favourites.has(f.family) ? '★' : '☆');
      const faceOf = () => (on && f.faces.find((x) => x.id === chosen.face)) || f.faces.find((x) => x.id === f.regular) || f.faces[0];
      const styles = f.faces.length > 1 ? h('select', {'aria-label': `Начертание ${f.family}`, onClick: (ev) => ev.stopPropagation(),
        onChange: (ev) => { chosen = {family: f.family, face: ev.target.value}; render(false); }},
      f.faces.map((x) => h('option', {value: x.id, selected: faceOf() && x.id === faceOf().id}, x.style))) : f.faces.length ? h('span', {class: 'small muted'}, f.faces[0].style) : null;
      const shown = !f.faces.length
        ? (loading.has(f.family) || queue.includes(f.family) ? h('span', {class: 'small muted'}, 'Скачиваем из Google Fonts…')
          : btn(`Скачать (${num((f.size || 0) / 1024 / 1024, 1)} МБ)`, (ev) => { ev.stopPropagation(); loading.add(f.family); render(false);
            download(f.family).finally(() => loading.delete(f.family)); }, 'btn-small'))
        : h('img', {class: 'lt-preview', src: preview(faceOf().id), alt: `${sampleText()} шрифтом ${f.family}`, loading: 'lazy'});
      const el = h('div', {class: 'lt-font' + (on ? ' picked' : ''), role: 'option', 'aria-selected': on ? 'true' : 'false', 'data-family': f.family,
        onClick: () => { if (!f.faces.length) return; chosen = {family: f.family, face: faceOf().id}; render(false); }},
      h('div', {class: 'lt-font-head'}, star, h('strong', {}, f.family), h('span', {class: 'pill'}, SOURCES[f.source] || f.source),
        h('span', {class: 'small muted'}, [KINDS[f.kind] || f.kind, f.scripts.map((s) => SCRIPTS[s] || s).join(', ')].filter(Boolean).join(' · ')),
        h('span', {class: 'spacer'}), styles,
        f.source === 'own' && f.faces.length ? btn('Удалить', (ev) => { ev.stopPropagation(); removeOwn(f); }, 'btn-small') : null),
      shown);
      if (!f.faces.length && observer) observer.observe(el);
      return el;
    }

    function render(reset = true) {
      if (reset) shownCount = PAGE;
      const found = families();
      fill(count, `Шрифтов: ${found.length} из ${catalogue.families.length}` + (catalogue.google.listed ? '' : ' · Google Fonts не загружен: кнопка ниже'));
      fill(list, found.length ? found.slice(0, shownCount).map(row) : h('p', {class: 'muted small'}, 'Под такой поиск и фильтры шрифтов нет.'));
      fill(more, found.length > shownCount ? btn(`Показать ещё (${found.length - shownCount})`, () => { shownCount += PAGE; render(false); }) : null);
      showGoogle();
    }

    function showGoogle() {
      const g = catalogue.google, s = g.download || {};
      fill(googleBox,
        h('div', {class: 'row'}, btn(g.listed ? 'Обновить список Google Fonts' : 'Загрузить список Google Fonts', async (ev) => {
          const self = ev.currentTarget;
          self.disabled = true;
          try { await post('/fonts/google/index'); await reload(); } catch (e) { fail(e); render(false); }
        }), g.listed ? h('span', {class: 'muted'}, `семейств Google: ${g.families}`) : h('span', {class: 'muted'}, 'нужен интернет; шрифты этого Mac и свои работают без него')),
        g.listed ? h('div', {class: 'row'}, btn(script.value ? `Скачать все Google: ${SCRIPTS[script.value]}` + (kind.value ? `, ${KINDS[kind.value].toLowerCase()}` : '')
          : 'Скачать все Google выбранной письменности', () => bulk(), '', !script.value || !!s.running),
        s.running ? h('span', {}, `скачано ${s.done} из ${s.total}…`) : s.total ? h('span', {class: 'muted'}, `скачано ${s.done} из ${s.total}`
          + (s.failed && s.failed.length ? `, не скачались: ${s.failed.length}` : '')) : null) : null);
    }

    async function bulk() {
      try { catalogue.google.download = await post('/fonts/google/download', {script: script.value, kind: kind.value || null}); } catch (e) { return fail(e); }
      showGoogle();
      clearInterval(polling);
      polling = setInterval(async () => {
        let s;
        try { s = await get('/fonts/google/status'); } catch (_) { return; }
        catalogue.google.download = s;
        if (!s.running) { clearInterval(polling); await reload(); } else showGoogle();
      }, 1000);
    }

    async function reload() {
      const download = catalogue.google.download;
      catalogue = await get('/fonts');
      if (download && !catalogue.google.download) catalogue.google.download = download;
      render(false);
    }

    /** The operator's font taken away: each face's file (a file with several faces goes with the first of them). */
    function removeOwn(f) {
      confirmBox('Удалить шрифт', `Удалить свой шрифт ${f.family} с этого компьютера? Надписи этим шрифтом попросят выбрать другой.`, 'Удалить', async () => {
        let removed = 0;
        for (const x of f.faces) {
          try { await del(`/fonts/own/${encodeURIComponent(x.id)}`); removed++; } catch (e) { if (!removed) return fail(e); }
        }
        if (chosen && chosen.family === f.family) chosen = null;
        await reload();
      });
    }

    ownInput.addEventListener('change', async () => {
      const file = ownInput.files && ownInput.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append('font', file);
      try {
        const got = await form('/fonts/own', fd);
        toast(`Шрифт добавлен: ${got.faces.map((x) => `${x.family} ${x.style}`).join(', ')}`, 'ok');
        chosen = {family: got.faces[0].family, face: got.faces[0].face};
        await reload();
      } catch (e) { fail(e); }
      ownInput.value = '';
    });
    let typing = null;
    text.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => render(false), 400); });
    search.addEventListener('input', () => render());
    for (const s of [source, script, kind]) s.addEventListener('change', () => render());
    render();
    modal('Шрифт надписи', h('div', {class: 'stack lt-font-window'},
      h('div', {class: 'row'}, h('label', {class: 'f lt-grow'}, h('span', {}, 'Образец'), text), h('label', {class: 'f lt-grow'}, h('span', {}, 'Поиск'), search)),
      h('div', {class: 'row lt-filters'}, source, script, kind),
      h('div', {class: 'row'}, h('span', {class: 'small'}, 'Свой шрифт:'), App.filePick(ownInput, 'Добавить файл шрифта')),
      count, list, more, googleBox,
      h('p', {class: 'small muted'}, 'Образец нарисован так, как буквы попадут в файл; буква, которой нет в шрифте, — красная. Шрифты Google скачиваются, '
        + 'когда видны в списке (до 2 МБ), остальные — кнопкой; скачанные остаются на этом компьютере. ★ — избранные (запоминает этот браузер).')),
    [{label: 'Отмена', run: (m) => m.close()},
      {label: 'Выбрать', cls: 'primary', run: async (m) => {
        const f = chosen && catalogue.families.find((x) => x.family === chosen.family && x.faces.some((y) => y.id === chosen.face));
        if (!f) return toast('Выберите шрифт в списке');
        m.close();
        await onPick({face: chosen.face, family: f.family, style: f.faces.find((y) => y.id === chosen.face).style});
      }}], () => { clearInterval(polling); if (observer) observer.disconnect(); });
  }

  // --- вкладка и слой ---------------------------------------------------------------------------------------------------------
  /** Надписи работы ``view``. ``o.act(op)`` отправляет операцию (true — принята), ``o.palette()`` — измеренные цвета титана работы,
      ``o.size(view)`` — размер работы в мм, ``o.scale()`` — экранных пикселей на мм картинки редактора (у фотогравировки слой знает это
      сам, :func:`attach`), ``o.drawn`` — слой рисует надписи сам (векторная работа), ``o.clean`` — цвет чистого титана для врезки,
      ``o.open()`` — открыта ли вкладка. ``o.pick(title, lab, entryId, onPick)``: the host's window of measured colours (the editor's,
      vector-colours.js: ΔE to ``lab``, time, where each colour is known from); a host without it shows the colours here to click. */
  function create(view, o) {
    let selected = null, entries = null, paletteError = null, drag = null, path = null, typing = null, built = null;
    let last = null;                          // the inscription chosen or changed last on this screen: a new one takes its font
    const layer = svgEl('g', {class: 'lt-layer'});
    const marks = svgEl('g', {class: 'lt-marks'});
    const list = h('div', {class: 'vw-ed-list lt-list'});
    const fields = h('div', {class: 'stack'});
    const about = h('p', {class: 'small muted'}, 'Надпись врезается в картинку: буквы гравируются своим цветом титана, вокруг них — зазор чистого титана; '
      + 'подложка (прямоугольник, овал или по контуру букв) — своим цветом или чистым титаном. Тащите надпись на картинке, круглая ручка поворачивает, '
      + 'квадратная — меняет размер, у пути тащатся его точки. Каждое изменение отменяется Ctrl+Z.');
    const blocked = h('div', {});
    const layers = h('div', {});
    const el = h('div', {class: 'vw-ed-pane lt-pane'},
      h('section', {class: 'vw-ed-section'}, h('div', {class: 'row'}, h('h4', {}, 'Надписи'), h('span', {class: 'spacer'}),
        btn('Добавить надпись', () => add(), 'primary')), about, blocked, list, layers),
      h('section', {class: 'vw-ed-section'}, fields));
    const texts = () => view.texts || [];
    const spec = () => texts().find((t) => t.id === selected) || null;

    async function act(op) {
      const ok = await o.act(op);
      return ok;
    }
    /** A new inscription in the middle of the work, in the font of the inscription chosen or changed last here; before any (after a reload)
        the server takes the font of the work's inscription changed last (lettering.last_font). */
    async function add() {
      const like = texts().find((t) => t.id === (selected || last));
      if (await act({op: 'text_add', text: like && like.font ? {font: like.font} : {}})) {
        const all = texts();
        if (all.length) select(all[all.length - 1].id);
      }
    }
    const change = (changes) => (selected ? act({op: 'text_set', id: selected, changes}) : Promise.resolve(false));

    function select(id) {
      selected = id;
      if (id) last = id;
      built = null;
      render();
    }

    async function loadPalette() {
      if (entries || paletteError) return;
      try { entries = [...await o.palette()].sort((a, b) => a.lab[0] - b.lab[0] || String(a.id).localeCompare(String(b.id))); }
      catch (e) { paletteError = e.message; }
      if (selected) renderFields(true);
    }

    // --- список -------------------------------------------------------------------------------------------------------------
    function renderList() {
      fill(blocked, view.export_blocked && /^inscription /.test(view.export_blocked) ? h('p', {class: 'alert warn small'}, I18N.tr(view.export_blocked)) : null);
      fill(list, texts().length ? texts().map((t, i) => h('button', {type: 'button', class: 'vw-ed-item lt-item' + (t.id === selected ? ' picked' : ''),
        'aria-pressed': t.id === selected ? 'true' : 'false', onClick: () => select(t.id === selected ? null : t.id)},
      t.srgb ? h('span', {class: 'sw', style: `background:${rgb(t.srgb)}`}) : h('span', {class: 'sw lt-none'}),
      h('strong', {}, `№ ${i + 1}`), h('span', {}, short(t.text)),
      h('span', {class: 'muted small'}, t.font ? t.font.family : ''),
      t.problem ? h('span', {class: 'pill bad'}, 'не выгравировать') : null))
        : h('p', {class: 'small muted'}, 'Надписей нет. «Добавить надпись» поставит её в середину работы; потом её можно передвинуть, повернуть и изменить.'));
      // a photo work says here which layers of the file engrave the letters (a vector work lists them among its layers)
      const timed = new Map(((view.time && view.time.layers) || []).map((l) => [l.index, l.seconds]));
      fill(layers, (view.text_layers || []).length ? h('div', {class: 'stack small'}, h('span', {class: 'muted'}, 'В файле LightBurn после картинки, светлые первыми:'),
        view.text_layers.map((l) => h('div', {class: 'vw-ed-item'}, h('span', {class: 'sw', style: `background:${rgb(l.srgb)}`}),
          h('strong', {}, `C${String(l.index).padStart(2, '0')}`), h('span', {class: 'muted'}, `${num(l.area_mm2, 1)} мм² · надписей ${l.texts.length}`
            + (timed.has(l.index) ? ` · ≈ ${App.duration(timed.get(l.index))}` : ''))))) : null);
    }

    // --- поля выбранной надписи -----------------------------------------------------------------------------------------------
    function number(label, key, step, extra = {}) {
      const input = h('input', {type: 'number', step, 'aria-label': label, 'data-field': key, ...extra});
      input.addEventListener('change', () => { if (input.value !== '') change({[key]: +input.value}); });
      return {key, el: h('label', {class: 'f lt-num'}, h('span', {}, label), input), input};
    }
    function choice(label, key, options) {
      const buttons = options.map(([value, name]) => btn(name, () => change({[key]: value})));
      return {key, buttons, values: options.map(([v]) => v), el: h('div', {class: 'stack'}, h('span', {class: 'small'}, label),
        h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': label}, buttons))};
    }
    function flag(label, key) {
      const input = h('input', {type: 'checkbox', 'aria-label': label, 'data-field': key});
      input.addEventListener('change', () => change({[key]: input.checked}));
      return {key, input, el: h('label', {class: 'row small'}, input, h('span', {}, label))};
    }

    /** A colour of the inscription (``key``): the backing (``allowNone``) may stay clean titanium. */
    function colourPart(label, key, allowNone) {
      const box = h('div', {class: o.pick ? 'row' : 'vw-swatches lt-swatches', role: 'group', 'aria-label': label});
      return {key, label, box, el: h('div', {class: 'stack'}, h('span', {class: 'small'}, label), box), allowNone};
    }

    function build() {
      const textArea = h('textarea', {rows: 3, 'aria-label': 'Текст надписи', class: 'lt-text'});
      textArea.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { typing = null; change({text: textArea.value}); }, TYPE_MS); });
      textArea.addEventListener('change', () => { clearTimeout(typing); typing = null; if (spec() && textArea.value !== spec().text) change({text: textArea.value}); });
      const font = btn('Шрифт…', () => { const t = spec(); if (t) fontWindow(t.font, t.text, (picked) => change({font: picked})); });
      const parts = {
        text: textArea, font,
        height: number('Высота букв, мм', 'height_mm', '0.1', {min: '0.3', max: '500'}),
        width: number('Ширина, %', 'width_pct', '1', {min: '10', max: '400'}),
        spacing: number('Интервал между буквами, мм', 'spacing_mm', '0.1'),
        line: number('Между строками, %', 'line_pct', '5', {min: '50', max: '400'}),
        align: choice('Выравнивание', 'align', ALIGNS),
        layout: choice('Расположение', 'layout', LAYOUTS),
        letters: choice('Буквы на кривой', 'letters', LETTERS),
        bend: number('Изгиб, %', 'bend', '1', {min: '-100', max: '100'}),
        radius: number('Радиус круга, мм', 'radius_mm', '0.5', {min: '0.5'}),
        start: number('Где на круге, °', 'start_deg', '1'),
        inside: flag('Внутри круга (читается против часовой)', 'inside'),
        offset: number('Место на пути, %', 'offset_pct', '1', {min: '0', max: '100'}),
        flip: flag('Путь в обратную сторону', 'flip'),
        rotation: number('Поворот, °', 'rotation', '1'),
        x: number('x, мм', 'x', '0.1'), y: number('y, мм', 'y', '0.1'),
        colour: colourPart('Цвет букв', 'entry_id', false),
        gap: number('Зазор вокруг букв, мм', 'gap_mm', '0.05', {min: '0', max: '20'}),
        backing: choice('Подложка', 'backing', BACKINGS),
        padding: number('Поле подложки, мм', 'padding_mm', '0.1', {min: '0'}),
        corner: number('Скругление углов, мм', 'corner_mm', '0.1', {min: '0'}),
        backingColour: colourPart('Цвет подложки', 'backing_entry_id', true),
        drawPath: btn('Нарисовать путь', () => startPath()),
        info: h('div', {class: 'small stack'}),
      };
      parts.el = h('div', {class: 'stack'},
        h('div', {class: 'row'}, h('h4', {}, 'Надпись'), h('span', {class: 'spacer'}), btn('Копия', () => act({op: 'text_copy', id: selected})),
          btn('Удалить', () => act({op: 'text_delete', id: selected}))),
        parts.info,
        h('label', {class: 'f'}, h('span', {}, 'Текст (Enter — новая строка)'), textArea),
        h('div', {class: 'row'}, font),
        h('div', {class: 'lt-grid'}, parts.height.el, parts.width.el, parts.spacing.el, parts.line.el), parts.align.el,
        parts.layout.el,
        h('div', {class: 'lt-grid', 'data-for': 'arc'}, parts.bend.el),
        h('div', {class: 'lt-grid', 'data-for': 'circle'}, parts.radius.el, parts.start.el), h('div', {'data-for': 'circle'}, parts.inside.el),
        h('div', {class: 'stack', 'data-for': 'path'}, h('div', {class: 'row'}, parts.drawPath, h('span', {class: 'small muted'}, 'щелчками или ведя мышью по картинке; Enter или двойной щелчок — готово')),
          h('div', {class: 'lt-grid'}, parts.offset.el), parts.flip.el),
        h('div', {'data-for': 'curved'}, parts.letters.el),
        h('div', {class: 'lt-grid'}, parts.rotation.el, parts.x.el, parts.y.el),
        parts.colour.el,
        h('h4', {}, 'Врезка в картинку'),
        h('div', {class: 'lt-grid'}, parts.gap.el), parts.backing.el,
        h('div', {class: 'lt-grid', 'data-for': 'backed'}, parts.padding.el, parts.corner.el),
        h('div', {'data-for': 'backed'}, parts.backingColour.el));
      return parts;
    }

    /** A colour's field: with the host's window (``o.pick``) the colour chosen and «Выбрать…», which opens it; without one every measured
        colour to click. */
    function fillColour(part, value) {
      if (!entries) return fill(part.box, h('p', {class: paletteError ? 'alert bad small' : 'muted small'}, paletteError || 'Загрузка цветов…'));
      const title = (e) => `${labText(e.lab)}` + (e.time_s_per_cm2 == null ? '' : ` · ${num(e.time_s_per_cm2, 1)} с/см²`);
      const clean = part.allowNone ? h('button', {type: 'button', class: 'vw-swatch lt-clean' + (value == null ? ' picked' : ''), title: 'Чистый титан: подложка не гравируется',
        'aria-label': 'Чистый титан', 'aria-pressed': value == null ? 'true' : 'false', onClick: () => change({[part.key]: null})}) : null;
      if (!o.pick) {
        return fill(part.box, clean, entries.map((e) => h('button', {type: 'button', class: 'vw-swatch' + (String(e.id) === String(value) ? ' picked' : ''),
          style: `background:${rgb(e.srgb)}`, 'data-entry': e.id, title: title(e), 'aria-label': title(e), 'aria-pressed': String(e.id) === String(value) ? 'true' : 'false',
          onClick: () => change({[part.key]: e.id})})));
      }
      if (!entries.length) return fill(part.box, clean, h('span', {class: 'small muted'}, 'Измеренных цветов титана для этой работы нет.'));
      const now = entries.find((e) => String(e.id) === String(value));
      fill(part.box, clean, now ? h('span', {class: 'vw-swatch picked', style: `background:${rgb(now.srgb)}`, 'data-entry': now.id, 'aria-hidden': 'true'}) : null,
        h('span', {class: 'small'}, now ? title(now) : value == null ? (part.allowNone ? '' : 'цвет не выбран') : 'этого цвета нет среди измеренных'),
        btn('Выбрать…', () => choose(part)));
    }
    /** The window of measured colours for a colour of the chosen inscription. ΔE is to the letters' colour: alternatives near it for the
        letters, how far a backing stands from them for the backing; while the letters have none, to the darkest measured colour, the one a
        new inscription takes. */
    function choose(part) {
      const t = spec();
      if (!t || !entries || !entries.length) return;
      const letters = entries.find((e) => String(e.id) === String(t.entry_id));
      o.pick(`${part.label} надписи № ${texts().indexOf(t) + 1} (ΔE — до ${letters ? 'цвета букв' : 'самого тёмного измеренного цвета'})`, (letters || entries[0]).lab,
        t[part.key], (id) => act({op: 'text_set', id: t.id, changes: {[part.key]: id}}));
    }

    function renderFields(paletteOnly = false) {
      const t = spec();
      if (!t) { built = null; return fill(fields, texts().length ? h('p', {class: 'small muted'}, 'Выберите надпись в списке или на картинке.') : null); }
      if (!built) { built = build(); fill(fields, built.el); }
      const p = built;
      fillColour(p.colour, t.entry_id);
      fillColour(p.backingColour, t.backing_entry_id);
      if (paletteOnly) return;
      const focused = document.activeElement;
      if (focused !== p.text && !typing) p.text.value = t.text;
      fill(p.font, `Шрифт: ${t.font ? `${t.font.family} ${t.font.style}` : 'по умолчанию'}…`);
      for (const part of [p.height, p.width, p.spacing, p.line, p.bend, p.radius, p.start, p.offset, p.rotation, p.x, p.y, p.gap, p.padding, p.corner]) {
        if (part.input !== focused) part.input.value = String(round(t[part.key], 3));
      }
      p.inside.input.checked = !!t.inside;
      p.flip.input.checked = !!t.flip;
      for (const part of [p.align, p.layout, p.letters, p.backing]) {
        part.buttons.forEach((b, i) => b.setAttribute('aria-pressed', part.values[i] === t[part.key] ? 'true' : 'false'));
      }
      const visible = {arc: t.layout === 'arc', circle: t.layout === 'circle', path: t.layout === 'path', curved: t.layout !== 'line',
        backed: t.backing !== 'none'};
      for (const box of p.el.querySelectorAll('[data-for]')) box.hidden = !visible[box.getAttribute('data-for')];
      p.corner.el.hidden = t.backing !== 'rect';
      fill(p.drawPath, path ? 'Готово' : t.points && t.points.length ? 'Нарисовать путь заново' : 'Нарисовать путь');
      const s = t.shown;
      fill(p.info,
        t.problem ? h('p', {class: 'alert bad'}, I18N.tr(t.problem)) : null,
        s && s.clipped ? h('p', {class: 'alert warn'}, 'Часть надписи выходит за край работы: там она обрезана.') : null,
        s && s.overflow ? h('p', {class: 'alert warn'}, 'Надпись не помещается на дуге или окружности: строка длиннее своей окружности или буквы заходят за центр. Увеличьте радиус (у дуги — уменьшите изгиб), уменьшите буквы или число строк.') : null,
        s && s.crowded && s.crowded.length ? h('p', {class: 'alert warn'}, `Буквы налезают друг на друга на крутом изгибе пути (${s.crowded.length > 1 ? 'строки' : 'строка'} ${s.crowded.join(', ')}): `
          + 'сделайте изгиб плавнее, уменьшите буквы, прибавьте интервал между ними или поверните путь в обратную сторону.') : null,
        s && s.empty && !t.problem ? h('p', {class: 'alert warn'}, 'У надписи нет букв, которые гравируются: введите текст.') : null,
        s ? h('p', {class: 'muted'}, `Буквы ${num(s.area_mm2, 1)} мм²` + (s.backing_mm2 ? ` · подложка ${num(s.backing_mm2, 1)} мм²` : '')
          + (t.srgb ? '' : ' · цвет букв не выбран')) : null);
    }

    function render() {
      renderList();
      renderFields();
      draw();
    }

    // --- слой на картинке ---------------------------------------------------------------------------------------------------
    const handleR = () => HANDLE_PX / Math.max(1e-6, pxPerMm());
    function draw() {
      while (layer.firstChild) layer.firstChild.remove();
      for (const t of texts()) {
        const s = t.shown;
        if (!s) continue;
        const g = svgEl('g', {class: 'lt-text' + (t.id === selected ? ' picked' : ''), 'data-text': t.id});
        if (o.drawn) {
          if (s.cut) g.append(svgEl('path', {class: 'lt-cut', d: s.cut, fill: o.clean, 'fill-rule': 'evenodd'}));
          if (s.backing && t.backing_srgb) g.append(svgEl('path', {class: 'lt-backing', d: s.backing, fill: rgb(t.backing_srgb), 'fill-rule': 'evenodd'}));
          if (s.letters) g.append(svgEl('path', {class: 'lt-letters', d: s.letters, fill: t.srgb ? rgb(t.srgb) : '#d32f2f', 'fill-rule': 'evenodd'}));
        } else {
          g.append(svgEl('path', {class: 'lt-hit', d: s.cut || s.letters || '', fill: 'rgba(0,0,0,0)'}));
        }
        if (o.open() && (t.id === selected || (drag && drag.t.id === t.id))) g.append(svgEl('path', {class: 'lt-outline', d: s.letters || '', fill: 'none'}));
        layer.append(g);
      }
      marks.remove();
      while (marks.firstChild) marks.firstChild.remove();
      const t = spec();
      if (t && t.shown && o.open()) {
        const f = t.shown.frame, r = handleR();
        marks.append(svgEl('polygon', {class: 'lt-frame', points: f.corners.map((c) => c.join(',')).join(' ')}));
        if (t.shown.guide) marks.append(svgEl('polyline', {class: 'lt-guide', points: t.shown.guide.map((c) => c.join(',')).join(' ')}));
        const top = mid(f.corners[0], f.corners[1]), up = unit(sub(f.corners[0], f.corners[3]));
        const knob = [top[0] + up[0] * r * 4, top[1] + up[1] * r * 4];
        marks.append(svgEl('line', {class: 'lt-stem', x1: top[0], y1: top[1], x2: knob[0], y2: knob[1]}),
          svgEl('circle', {class: 'lt-handle', 'data-handle': 'rotate', cx: knob[0], cy: knob[1], r}),
          svgEl('rect', {class: 'lt-handle', 'data-handle': 'size', x: f.corners[2][0] - r, y: f.corners[2][1] - r, width: 2 * r, height: 2 * r}));
        if (t.layout === 'path') {
          absolute(t).forEach(([x, y], i) => marks.append(svgEl('circle', {class: 'lt-handle lt-point', 'data-handle': 'point', 'data-index': i, cx: x, cy: y, r: r * 0.8})));
        }
      }
      if (path) {
        path.line = svgEl('polyline', {class: 'lt-drawn', points: drawnPoints()});
        marks.append(path.line);
        for (const [x, y] of path.points) marks.append(svgEl('circle', {class: 'lt-point', cx: x, cy: y, r: handleR() * 0.7}));
      }
      layer.append(marks);
    }
    const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const unit = (v) => { const l = Math.hypot(v[0], v[1]) || 1; return [v[0] / l, v[1] / l]; };
    /** The points of a path in the work's mm: relative to the inscription's place, turned with it. */
    const absolute = (t) => (t.points || []).map((p) => { const [u, v] = turn(p, t.rotation); return [t.x + u, t.y + v]; });

    // --- mouse: drag an inscription, its handles, a path's points; draw a path by clicks or freehand --------------------------------
    /** Pointer down at ``mm``: true when the layer takes the gesture (an inscription, a handle, a path being drawn: a press may start a
        freehand stroke of it). */
    function down(ev, mm) {
      if (!o.open()) return false;
      if (path) { path.stroke = {points: [mm], moved: false}; return true; }
      const target = ev.target && ev.target.closest ? ev.target : null;
      const handle = target && target.closest('[data-handle]');
      const hit = target && target.closest('[data-text]');
      const t = handle ? spec() : hit ? texts().find((x) => x.id === hit.getAttribute('data-text')) : null;
      if (!t || !t.shown) return false;
      if (t.id !== selected) { selected = last = t.id; built = null; renderList(); renderFields(); }
      const kind = handle ? handle.getAttribute('data-handle') : 'move';
      drag = {kind, start: mm, t, index: handle ? Number(handle.getAttribute('data-index')) : null, moved: false, at: mm};
      draw();
      return true;
    }
    function move(ev, mm) {
      if (path && path.stroke) {
        const s = path.stroke;
        s.moved = s.moved || Math.hypot(mm[0] - s.points[0][0], mm[1] - s.points[0][1]) * pxPerMm() > 3;
        s.points.push(mm);
        if (path.line) path.line.setAttribute('points', drawnPoints());
        return true;
      }
      if (!drag) return false;
      drag.at = mm;
      drag.moved = drag.moved || Math.hypot(mm[0] - drag.start[0], mm[1] - drag.start[1]) * pxPerMm() > 3;
      const g = [...layer.querySelectorAll('g')].find((x) => x.getAttribute('data-text') === drag.t.id);
      const a = drag.t.shown.frame.anchor;
      if (drag.kind === 'move') {
        g.setAttribute('transform', `translate(${round(mm[0] - drag.start[0], 4)} ${round(mm[1] - drag.start[1], 4)})`);
      } else if (drag.kind === 'rotate') {
        g.setAttribute('transform', `rotate(${round(angle(drag, ev), 3)} ${a[0]} ${a[1]})`);
      } else if (drag.kind === 'size') {
        const k = factor(drag);
        g.setAttribute('transform', `translate(${a[0]} ${a[1]}) scale(${round(k, 4)}) translate(${-a[0]} ${-a[1]})`);
      } else if (drag.kind === 'point') {
        const pts = absolute(drag.t);
        pts[drag.index] = mm;
        const line = marks.querySelector('polyline') || svgEl('polyline', {class: 'lt-guide'});
        line.setAttribute('points', pts.map((c) => c.join(',')).join(' '));
        if (!line.parentNode) marks.append(line);
      }
      return true;
    }
    const angle = (d, ev) => {
      const a = d.t.shown.frame.anchor;
      const turned = (Math.atan2(d.at[1] - a[1], d.at[0] - a[0]) - Math.atan2(d.start[1] - a[1], d.start[0] - a[0])) * 180 / Math.PI;
      return ev && ev.shiftKey ? Math.round(turned / 15) * 15 : turned;
    };
    const factor = (d) => {
      const a = d.t.shown.frame.anchor;
      return clamp(Math.hypot(d.at[0] - a[0], d.at[1] - a[1]) / Math.max(1e-6, Math.hypot(d.start[0] - a[0], d.start[1] - a[1])), 0.05, 20);
    };
    function up(ev, mm) {
      if (path && path.stroke) {
        const s = path.stroke;
        path.stroke = null;
        if (!s.moved) { draw(); return false; }            // a press without a move: its click places a point
        if (mm) s.points.push(mm);
        addPoints(strokePoints(s.points));
        return true;                                       // the end of the stroke is not a click
      }
      if (!drag) return false;
      const d = drag;
      drag = null;
      if (mm) d.at = mm;
      if (!d.moved) { draw(); return true; }
      const t = d.t, a = t.shown.frame.anchor;
      // a turn and a size are about the frame's anchor, as the layer showed them: the inscription's place moves with them when it is not there
      if (d.kind === 'move') change({x: round(t.x + d.at[0] - d.start[0], 3), y: round(t.y + d.at[1] - d.start[1], 3)});
      else if (d.kind === 'rotate') {
        const turned = angle(d, ev), [u, v] = turn([t.x - a[0], t.y - a[1]], turned);
        change({rotation: round(((t.rotation + turned + 540) % 360) - 180, 2), x: round(a[0] + u, 3), y: round(a[1] + v, 3)});
      } else if (d.kind === 'size') {
        const k = factor(d);
        const changes = {height_mm: round(clamp(t.height_mm * k, 0.3, 500), 3), spacing_mm: round(t.spacing_mm * k, 3),
          x: round(a[0] + k * (t.x - a[0]), 3), y: round(a[1] + k * (t.y - a[1]), 3)};
        if (t.backing !== 'none') Object.assign(changes, {padding_mm: round(t.padding_mm * k, 3), corner_mm: round(t.corner_mm * k, 3)});
        if (t.layout === 'circle') changes.radius_mm = round(Math.max(0.5, t.radius_mm * k), 3);
        if (t.layout === 'path') changes.points = t.points.map(([x, y]) => [round(x * k, 3), round(y * k, 3)]);
        change(changes);
      } else if (d.kind === 'point') {
        const pts = absolute(t);
        pts[d.index] = d.at;
        change(placed(pts, t.rotation));
      }
      return true;
    }
    /** A path through absolute points as the fields of an inscription: its place the first point, the others relative to it, unturned. */
    function placed(pts, rotation = 0) {
      const [x0, y0] = pts[0];
      return {x: round(x0, 3), y: round(y0, 3), points: pts.map(([x, y]) => turn([x - x0, y - y0], -rotation).map((v) => round(v, 3)))};
    }
    /** A click at ``mm`` while the tab is open: a point of the path being drawn (the second click of a double click ends the path: its
        first click placed the last point), or a click beside every inscription leaves the one chosen. */
    function click(ev, mm) {
      if (!o.open()) return false;
      if (path) {
        if (ev.detail >= 2) finishPath();
        else addPoints([mm]);
        return true;
      }
      const hit = ev.target && ev.target.closest ? ev.target.closest('[data-text]') : null;
      if (!hit && selected && !(ev.target && ev.target.closest && ev.target.closest('[data-handle]'))) select(null);
      return true;
    }
    /** The path being drawn on the picture: its points so far and the stroke under the pointer. */
    const drawnPoints = () => path.points.concat(path.stroke ? path.stroke.points : []).map((c) => c.join(',')).join(' ');
    /** Points (mm) added to the path being drawn; one on its last point (within a pixel on screen) is no new point. */
    function addPoints(pts) {
      for (const p of pts) {
        const q = p.map((v) => round(v, 3)), last = path.points[path.points.length - 1];
        if (!last || Math.hypot(q[0] - last[0], q[1] - last[1]) * pxPerMm() >= 1) path.points.push(q);
      }
      draw();
    }
    /** The samples of a freehand stroke as points of the path: simplified (STROKE_PX, STROKE_OF_HEIGHT) to what the path has room for. */
    function strokePoints(samples) {
      const t = spec(), room = Math.max(2, MAX_POINTS - path.points.length);
      let tol = Math.max(STROKE_PX / Math.max(1e-6, pxPerMm()), t ? t.height_mm * STROKE_OF_HEIGHT : 0), pts = simplify(samples, tol);
      while (pts.length > room) { tol *= 2; pts = simplify(samples, tol); }
      return pts;
    }
    /** Enter while a path is drawn ends it, as «Готово» does; in a field Enter stays the field's (a new line of the text). */
    function pathKey(ev) {
      if (!path || ev.key !== 'Enter') return;
      if (!el.isConnected) return stopPath();
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;
      if (document.querySelector('.modal-bg')) return;
      ev.preventDefault();                                 // a focused «Готово» would start a new path on its own Enter
      finishPath();
    }
    function startPath() {
      if (path) return finishPath();
      path = {points: [], stroke: null, line: null};
      document.addEventListener('keydown', pathKey);
      toast('Щёлкайте по картинке точками пути или ведите мышью с нажатой кнопкой; Enter, двойной щелчок или «Готово» — путь готов, Esc — отменить');
      renderFields();
      draw();
    }
    function stopPath() {
      path = null;
      document.removeEventListener('keydown', pathKey);
    }
    function finishPath() {
      const pts = path ? path.points : [];
      stopPath();
      if (pts.length < 2) { toast('Путь — две точки или больше'); renderFields(); return draw(); }
      change({layout: 'path', rotation: 0, ...placed(pts)});
    }
    /** Escape: a path being drawn is dropped; otherwise the chosen inscription is left. */
    function escape() {
      if (path) { stopPath(); renderFields(); draw(); return true; }
      if (drag) { drag = null; draw(); return true; }
      if (selected) { select(null); return true; }
      return false;
    }

    // --- фотогравировка: слой поверх прогноза ------------------------------------------------------------------------------
    let photoSvg = null, photoBox = null, photoSkip = false;
    /** The layer over a photo work's look: ``stage`` holds the preview, the picture and its look side by side (``gap`` px between, each
        ``cols`` px wide), contained and centred in its box. The layer is an SVG over the same box, contained and centred the same way, in
        the work's mm with its origin at the look's corner. */
    function attach(stage, cols, gap) {
      if (!stage || !cols) return;
      const size = o.size(view), gapMm = gap * size.width / cols;
      photoBox = [-(size.width + gapMm), 0, 2 * size.width + gapMm, size.height];
      const svg = svgEl('svg', {class: 'lt-over' + (o.open() ? ' open' : ''), viewBox: photoBox.map((v) => round(v, 4)).join(' '),
        preserveAspectRatio: 'xMidYMid meet', 'aria-hidden': 'true'});
      svg.append(layer);
      stage.append(svg);
      photoSvg = svg;
      const toMm = (ev) => {
        const r = svg.getBoundingClientRect(), s = photoScale(), [x0, , w, hh] = photoBox;
        return [round(x0 + (ev.clientX - r.left - (r.width - w * s) / 2) / s, 3), round((ev.clientY - r.top - (r.height - hh * s) / 2) / s, 3)];
      };
      svg.addEventListener('pointerdown', (ev) => { if (down(ev, toMm(ev))) { ev.preventDefault(); try { svg.setPointerCapture(ev.pointerId); } catch (_) { /* уже отпущен */ } } });
      svg.addEventListener('pointermove', (ev) => move(ev, toMm(ev)));
      svg.addEventListener('pointerup', (ev) => { if (up(ev, toMm(ev))) photoSkip = true; });
      svg.addEventListener('click', (ev) => { if (photoSkip) { photoSkip = false; return; } click(ev, toMm(ev)); });
      draw();
    }
    /** Screen pixels per mm of a photo work's look. */
    function photoScale() {
      const r = photoSvg.getBoundingClientRect();
      return Math.min(r.width / photoBox[2], r.height / photoBox[3]) || 1;
    }
    const pxPerMm = () => (photoSvg ? photoScale() : o.scale());

    /** The work as it is now (after any operation, undo or redo): the list, the chosen inscription's fields and the layer. */
    function update(next) {
      view = next;
      if (selected && !spec()) { selected = null; built = null; }
      loadPalette();
      if (photoSvg) photoSvg.setAttribute('class', 'lt-over' + (o.open() ? ' open' : ''));
      render();
    }
    function opened() {
      if (photoSvg) photoSvg.setAttribute('class', 'lt-over' + (o.open() ? ' open' : ''));
      if (!o.open() && path) stopPath();
      draw();
    }

    loadPalette();
    render();
    return {el, layer, update, down, move, up, click, escape, attach, opened, redraw: draw, busy: () => !!drag || !!path, selected: () => selected};
  }

  return {create, fontWindow, SCRIPTS, KINDS, SOURCES};
})();
