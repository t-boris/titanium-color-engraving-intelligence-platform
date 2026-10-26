/* Векторная работа из фотографии, редактор цветов (REQ-043..REQ-049, DEC-001, DEC-075..DEC-077): одна большая картинка в
   цветах титана и панель рядом (под картинкой на узком экране) — инструменты (кисть, пипетка, выделение), что меняет щелчок
   кистью, активный цвет, палитра всех измеренных цветов, слои титана, исходные цвета, итоги, отмена и повтор. Каждый
   исходный цвет раскрашен сразу; цвет дальше допуска ΔE помечается и по запросу обводится на картинке, файл он не
   блокирует. Наведение обводит ровно то, что изменит щелчок (для заливки — области, которые назвал сервер). Масштаб и сдвиг
   меняют viewBox картинки. После каждого действия сервер возвращает работу целиком, и картинка перекрашивается на месте:
   масштаб, сдвиг, инструмент, активный цвет и выделение сохраняются; новая версия разбиения загружается заново.
   Слить области в один контур можно только связному выделению: кто с кем граничит, экран спрашивает у сервера один раз на
   версию разбиения (DEC-080); сервер всё равно проверяет каждое слияние.
   Фотозоны (REQ-073): выделенные области (щелчок, Shift+щелчок или лассо — обвести мышью инструментом «Выделение») становятся фотозоной —
   они гравируются фотогравировкой картинки работы; на картинке зона показана такой, какой выйдет (её области прозрачны над её картинкой),
   её вид и шкала — во вкладке «Фото» (vector-photo.js). Сдвиг при «Выделении» — пробел+перетаскивание или средняя кнопка мыши. */
'use strict';
const VectorEditor = (() => {
  const {h, fill, btn, get, pill, toast, num, labText, steadiness, STEADY, originText} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const EXCLUDED = '#e6e6e6';                 // исключённое не гравируется: остаётся только чистка
  const MISSING = '#d32f2f';                  // выбранного цвета титана больше нет среди измерений: штриховка
  const BASIS = {chart: 'по карте', clean: 'по чистому титану', 'as-shot': 'как снято, без привязки'};
  const TOOLS = [['brush', 'Кисть'], ['pipette', 'Пипетка'], ['select', 'Выделение']];
  const SCOPES = [['region', 'Участок'], ['colour', 'Весь исходный цвет'], ['fill', 'Заливка похожих']];
  const VIEWS = [['titanium', 'Титан'], ['source', 'Исходные цвета'], ['original', 'Оригинал']];
  const SIMILARITY = 8;                       // ΔE заливки похожих по умолчанию
  const SEE_THROUGH = 'rgba(0,0,0,0)';        // область фотозоны: видна картинка зоны под ней, а наведение и щелчок по ней работают
  const LASSO_STEP = 3;                       // экранных пикселей между точками лассо
  const svgCache = new Map();
  const paletteCache = new Map();
  const nearCache = new Map();
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const chip = (c, title) => h('span', {class: 'sw', style: `background:${rgb(c)}`, title: title || ''});
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} кГц · ${num(p.speed, 0)} мм/с · Q-Pulse ${num(p.pulse_width, 0)} нс`
    + (p.line_interval == null ? '' : ` · шаг ${num(p.line_interval, 3)} мм`) + ` · ${p.passes ?? 1} проход(а)` + (p.cross_hatch ? ' · cross-hatch' : '');
  const seconds = (s) => (s == null ? 'не оценено' : num(s, 1) + ' с/см²');
  const mmList = (list) => list.map((v) => num(v, 1)).join(' и ') + ' мм';
  /** Длина строк слоя (DEC-107) — короткая отметка «↔ 13,3 мм» в строке слоя; цветом предупреждения, когда цвет рецепта при такой длине
      не измерен; полный текст — в подсказке. */
  function sizeNote(size) {
    const says = sizeSays(size);
    // on a line of the layers' list: muted when the colour was measured at this length, in the warning colour when it was not
    return says ? h('span', {class: 'vw-rows ' + (size.how === 'measured' ? 'muted' : 'warn vw-bad'), title: says, 'aria-label': says}, `↔ ${num(size.row_mm, 1)} мм`) : null;
  }
  function sizeSays(size) {
    if (!size || size.row_mm == null) return null;
    const rows = `строки ${num(size.row_mm, 1)} мм`;
    return size.how === 'measured' ? `${rows}: цвет рецепта измерен при ${mmList(size.from_mm)}`
      : size.how === 'between' ? `${rows}: цвет взят между измерениями при ${mmList(size.from_mm)}`
        : size.how === 'outside' ? `${rows}: цвет рецепта измерен при ${mmList(size.measured_mm)}, при такой длине — нет; на титане может выйти другим`
          : `${rows}: при какой длине измерен цвет рецепта, неизвестно`;
  }
  /** A control on a line of a list (a box to tick, a swatch to press) works by itself: its click, Enter or Space does not open the line. */
  function inRow(el) {
    el.addEventListener('click', (ev) => ev.stopPropagation());
    el.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') ev.stopPropagation(); });
    return el;
  }
  const titled = (el, text) => { el.title = text; return el; };
  const SIZE_ABOUT = 'Цвет на титане зависит от длины строк заливки (DEC-107): лазер возвращается к точке через строку, и на коротких строках титан '
    + 'не успевает остыть. Цвет слоя взят при длине его строк: измеренный, между двумя измеренными или — вне измеренных размеров — у ближайшего, '
    + 'и тогда на титане он может выйти другим. Пластина «Размер заливки» измеряет рецепты при нужных ширинах.';
  const de = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);       // CIE76, как на сервере
  const PALETTE_PAGE = 60;                         // squares of the palette shown at once, the nearest first
  const duration = (s) => (s == null ? 'не оценено' : s >= 3600 ? `${Math.floor(s / 3600)} ч ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} мин`
    : s >= 60 ? `${Math.floor(s / 60)} мин ${String(Math.round(s % 60)).padStart(2, '0')} с` : `${Math.round(s)} с`);
  const area = (mm2) => (mm2 == null ? '—' : mm2 >= 100 ? `${num(mm2 / 100, 2)} см²` : `${num(mm2, 1)} мм²`);
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const setClass = (el, cls, on) => (on ? el.classList.add(cls) : el.classList.remove(cls));
  const mark = (set, value, on) => (on ? set.add(value) : set.delete(value));
  const same = (a, b) => a != null && b != null && String(a) === String(b);   // номера цветов палитры — текст, сравниваются как текст
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  /** How a list of source colours is narrowed and sorted: the editor's «Цвета» and the window «Подробно по цветам» (DEC-090). */
  const COLOUR_FILTER = {key: 'state', label: 'Какие цвета', options: [['far', 'вне допуска'], ['hand', 'вручную'], ['excluded', 'не гравируются'], ['missing', 'нет цвета титана']],
    test: (c, v) => (v === 'far' ? !!c.outside_tolerance : v === 'hand' ? c.status === 'hand' || c.status === 'accepted' : c.status === v)};
  const byIndex = (a, b) => Number(a.index) - Number(b.index);
  const COLOUR_SORTS = [['order', 'По номеру', byIndex], ['far', 'Сначала дальние (ΔE)', (a, b) => (b.delta_e ?? -1) - (a.delta_e ?? -1) || byIndex(a, b)],
    ['area', 'Больше площадь', (a, b) => (b.pixels ?? 0) - (a.pixels ?? 0) || byIndex(a, b)]];

  /** Рисунок границ меняют версия разбиения и гладкость линий (REQ-052): области и цвета при этом те же. */
  const geometryKey = (j) => `${j.document.version}:${j.smoothing_mm || 0}`;

  /** Разбиение в исходных цветах (SVG) один раз на рисунок границ: геометрия не приходит с каждым ответом. */
  async function splitSvg(j) {
    const key = `${j.id}:${geometryKey(j)}`;
    if (!svgCache.has(key)) {
      const res = await fetch(`/api/vector/${j.id}/split.svg`);
      if (!res.ok) throw new Error('Разбиение не загрузилось');
      svgCache.set(key, await res.text());
    }
    const doc = new DOMParser().parseFromString(svgCache.get(key), 'image/svg+xml');
    const svg = document.importNode(doc.documentElement, true);
    svg.removeAttribute('width'); svg.removeAttribute('height');
    return svg;
  }

  /** Все измеренные цвета лазера, линзы и титана работы; признак «берёт ли автоматика» зависит от фильтров работы. */
  async function palette(j) {
    const key = `${j.id}:${JSON.stringify(j.settings)}`;
    if (!paletteCache.has(key)) paletteCache.set(key, get(`/vector/${j.id}/palette`));
    try { return await paletteCache.get(key); } catch (e) { paletteCache.delete(key); throw e; }
  }

  /** Какие области граничат друг с другом, один раз на версию документа (DEC-080): слить можно только связанное выделение. */
  async function neighbours(j) {
    const key = `${j.id}:${j.document.version}`;
    if (!nearCache.has(key)) nearCache.set(key, get(`/vector/${j.id}/neighbours`));
    try { return await nearCache.get(key); } catch (e) { nearCache.delete(key); throw e; }
  }

  /** Чем окрашена область: исключённая — ничем; свой цвет области важнее цвета её исходного цвета, даже исключённого. */
  function resolver(j) {
    const colours = new Map(j.colours.map((c) => [Number(c.index), c]));
    const exColours = new Set((j.colouring.excluded_colours || []).map(Number)), exRegions = new Set(j.colouring.excluded_regions || []);
    const own = j.colouring.regions || {};
    const tol = j.settings.tolerance_de;
    const zones = new Map((j.zones || []).flatMap((z) => z.regions.map((rid) => [rid, z])));
    return (rid, k) => {
      const c = colours.get(k) || null;
      if (zones.has(rid)) return {c, zone: zones.get(rid)};               // фотозона: гравируется картинкой, не цветом
      if (exRegions.has(rid)) return {c, excluded: true};
      if (own[rid] != null) {
        const entry = j.entries[own[rid]];
        return entry ? {c, entry, entryId: own[rid], own: true, far: !!c && tol != null && de(c.lab, entry.lab) > tol} : {c, missing: true, own: true};
      }
      if (!c || exColours.has(k) || c.status === 'excluded') return {c, excluded: true};
      const entry = c.entry_id == null ? null : j.entries[c.entry_id];
      return entry ? {c, entry, entryId: c.entry_id, far: !!c.outside_tolerance} : {c, missing: true};
    };
  }

  // клавиши действуют только для редактора, который сейчас на экране
  let current = null;
  document.addEventListener('keydown', (ev) => { if (current) current.key(ev); });
  document.addEventListener('keyup', (ev) => { if (current) current.keyup(ev); });

  /** Редактор работы j; run(op) отправляет одно действие и обновляет экран (возвращает true, если сервер его принял). */
  function create(j, run, tools = {}) {           // tools.pick(j, title, sourceLab, entryId, onPick): the window that chooses a titanium colour (vector-colours.js)
    const id = j.id;
    const state = {tool: 'brush', scope: 'region', similarity: SIMILARITY, active: null, view: 'titanium', far: false, ref: null,
      selection: new Set(), layers: new Set(), colours: new Set()};
    let lookup = resolver(j);
    let svg = null, loadedVersion = null, loadedWidth = null, missId = '';
    let paths = new Map(), colourOf = new Map(), byColour = new Map(), byEntry = new Map();
    let vb = {x: 0, y: 0, w: j.document.size_mm.width, h: j.document.size_mm.height};
    let entries = null, paletteError = null, paletteKey = null;
    let paletteShown = PALETTE_PAGE;
    let near = null, nearKey = null, nearFailed = false;     // область → соседи по границе в текущей версии разбиения (DEC-080)
    let hover = null, hot = [], farCount = 0, pending = 0, spaceHeld = false, sideTab = null, ready = false;
    let zonePics = null;                                     // <g> с картинками фотозон под областями
    let borders = [], bordersOf = new Map();                 // every border of the split once: its path and the regions on its sides
    let lines = null;                                        // <g> of the outlines above the regions: the zones, the hover, the selection
    const reach = new Map();
    let reachTimer = null, sortTimer = null;

    // --- разметка -------------------------------------------------------------------------------------------------------
    const stage = h('div', {class: 'vw-ed-stage tool-brush', role: 'group', 'aria-label': 'Картинка работы: наведите на область, щёлкните, чтобы изменить'});
    const tip = h('div', {class: 'vw-ed-tip', hidden: true, 'aria-hidden': 'true'});
    const loading = h('p', {class: 'vw-ed-loading muted small'}, 'Загрузка разбиения…');
    stage.append(loading, tip);
    const viewButtons = VIEWS.map(([v, label]) => btn(label, () => setView(v)));
    const zoomLabel = h('span', {class: 'vw-ed-zoom small muted'});
    const undoBtn = btn('Отменить', () => undoRedo('undo')), redoBtn = btn('Повторить', () => undoRedo('redo'));
    const bar = h('div', {class: 'vw-ed-bar'},
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Что показать на картинке'}, viewButtons),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Масштаб'},
        h('button', {type: 'button', class: 'btn', 'aria-label': 'Уменьшить', title: 'Уменьшить', onClick: () => zoomBy(1 / 1.5)}, '−'), zoomLabel,
        h('button', {type: 'button', class: 'btn', 'aria-label': 'Увеличить', title: 'Увеличить', onClick: () => zoomBy(1.5)}, '+'),
        btn('Вписать', () => fit())),
      h('span', {class: 'spacer'}),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Отмена и повтор'}, undoBtn, redoBtn));
    const totals = h('p', {class: 'vw-ed-totals small'});

    const toolButtons = TOOLS.map(([t, label]) => btn(label, () => setTool(t)));
    const scopeButtons = SCOPES.map(([s, label]) => btn(label, () => setScope(s)));
    const simNumber = h('input', {type: 'number', step: '0.5', min: '0.5', max: '50', value: state.similarity, 'aria-label': 'Похожесть, ΔE'});
    const simRange = h('input', {type: 'range', step: '0.5', min: '0.5', max: '30', value: state.similarity, 'aria-label': 'Похожесть, ΔE, ползунком'});
    simNumber.addEventListener('change', () => setSimilarity(simNumber.value));
    simRange.addEventListener('input', () => setSimilarity(simRange.value));
    const simBox = h('div', {class: 'vw-ed-sim', hidden: true}, h('span', {class: 'small'}, 'Похожесть, ΔE'), h('div', {class: 'row'}, simRange, simNumber),
      h('span', {class: 'small muted'}, 'заливка идёт по соседям, чей исходный цвет ближе этого ΔE к цвету щёлкнутой области; исключённые области её останавливают'));
    const scopeBox = h('div', {class: 'vw-ed-scope'}, h('h4', {}, 'Щелчок кистью меняет'),
      h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Что меняет щелчок кистью'}, scopeButtons), simBox);
    const selectionBox = h('section', {class: 'vw-ed-section'});
    const selectionSlots = {brush: h('div', {}), photo: h('div', {})};   // the selection and its actions: on «Кисть», or on «Фото» while it is open
    const autoBtn = btn('Авто', () => setActive(null));
    autoBtn.setAttribute('title', 'Кисть возвращает автоматический выбор цвета');
    const activeBox = h('div', {class: 'vw-ed-active'});
    const paletteHead = h('h4', {}, 'Палитра'), paletteNote = h('p', {class: 'small muted'});
    const grid = h('div', {class: 'vw-swatches vw-ed-palette', role: 'group', 'aria-label': 'Измеренные цвета титана'});
    const paletteFoot = h('div', {class: 'lst-foot'});
    // the layers and the source colours are short lists (DEC-090): one line each, what it is and its other actions under it on a click,
    // search and sort; pages of 30, so that a work's colours (29 at most) are edited on one page
    const layerList = App.list({id: 'vw.ed.layers', items: [], page: 30, key: (x) => x.key, row: layerRow, details: layerDetails, search: (x) => x.search,
      sorts: [['order', 'По порядку', (a, b) => a.pos - b.pos], ['area', 'Больше площадь', (a, b) => (b.area ?? -1) - (a.area ?? -1) || a.pos - b.pos],
        ['time', 'Дольше гравировка', (a, b) => (b.seconds ?? -1) - (a.seconds ?? -1) || a.pos - b.pos]],
      empty: 'Слоёв цвета нет: всё исключено.'});
    const colourList = App.list({id: 'vw.ed.colours', items: [], page: 30, key: (c) => String(c.index), row: colourRow, details: colourDetails,
      rowClass: (c) => (c.status === 'excluded' ? 'excluded' : ''),
      actions: colourActions, search: (c) => `№ ${Number(c.index) + 1}`, filters: [COLOUR_FILTER], sorts: COLOUR_SORTS, empty: 'Нет исходных цветов под такой выбор.'});
    const layersBox = h('div', {class: 'vw-ed-list vw-ed-layers'}, layerList.el), layerMerge = h('div', {}), layersAbout = h('div', {});
    const farBox = h('input', {type: 'checkbox', onChange: (ev) => { state.far = ev.target.checked; syncSvgClass(); }});
    const farNote = h('p', {class: 'small muted'});
    const coloursBox = h('div', {class: 'vw-ed-list'}, h('p', {class: 'small muted'}, 'Исходный цвет — цвет области на вашей картинке; справа цвет титана, которым он '
      + 'будет выгравирован. «Заменить» выбирает другой цвет титана: у каждого видно, откуда он известен (тесты и работы) и насколько стабилен. По щелчку на строке — '
      + 'откуда известен цвет, «Автоматически» и «Не гравировать»: все области этого цвета уйдут из файла, останется только чистка.'), colourList.el);
    const colourMerge = h('div', {});
    let layerRegions = new Map();                            // the key of a layer's line -> the regions it outlines on the picture
    outlineRows(layerList, (key) => (layerRegions.get(key) || (() => []))());
    outlineRows(colourList, (key) => byColour.get(Number(key)) || []);
    const photo = VectorPhoto.create(j, {act: (op) => act(op), select: (ids) => selectOnly(ids), outline: (ids) => (ids ? setHot(ids) : refreshHover())});
    // надписи врезаются в картинку: слой рисует врезку цветом чистого титана, подложку и буквы их цветами (inscriptions-in-works)
    const lettering = Lettering.create(j, {act: (op) => act(op), palette: () => palette(j), size: (v) => v.document.size_mm, scale: () => frame().s,
      drawn: true, clean: EXCLUDED, open: () => sideTab === 'texts',
      pick: tools.pick ? (title, lab, entryId, onPick) => tools.pick(j, title, lab, entryId, onPick) : null});
    // панель на пять вкладок, чтобы не прокручивать: кисть и цвет, слои титана, исходные цвета (DEC-085), фотозоны (REQ-073), надписи
    const sideTabs = App.tabs([
      ['brush', 'Кисть', h('div', {class: 'vw-ed-pane'},
        h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Инструмент'),
          h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Инструмент'}, toolButtons),
          h('p', {class: 'small muted'}, 'Alt+щелчок кистью — пипетка.'), scopeBox),
        selectionSlots.brush,
        h('section', {class: 'vw-ed-section'}, h('div', {class: 'row'}, h('h4', {}, 'Активный цвет'), h('span', {class: 'spacer'}), autoBtn), activeBox),
        h('section', {class: 'vw-ed-section'}, paletteHead, paletteNote, grid, paletteFoot))],
      ['layers', 'Слои', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Слои титана'), layersAbout, layersBox, layerMerge))],
      ['colours', 'Цвета', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Исходные цвета'),
        h('label', {class: 'row small'}, farBox, h('span', {}, 'Показать далёкие от оригинала')), farNote, coloursBox, colourMerge))],
      ['photo', 'Фото', h('div', {class: 'vw-ed-pane'}, selectionSlots.photo, photo.el)],
      ['texts', 'Надписи', lettering.el]],
      {initial: 'brush', remember: 'vw.edtab', label: 'Панель редактора', prefix: 'vw-ed-tab', onSelect: (id) => {
        sideTab = id;
        syncSvgClass();
        lettering.opened();
        if (id === 'texts') { hover = null; tip.hidden = true; setHot([]); }
        (id === 'photo' ? selectionSlots.photo : selectionSlots.brush).append(selectionBox);
        if (ready && id === 'photo') setTool('select');       // on «Фото» a click selects (the brush is on «Кисть», out of sight)
      }});
    const panel = h('aside', {class: 'vw-ed-panel', 'aria-label': 'Инструменты и цвета'}, sideTabs.list, h('div', {class: 'vw-ed-panes'}, sideTabs.panels));
    const el = h('div', {class: 'vw-editor'},
      h('div', {class: 'vw-ed-main'}, bar, totals, stage,
        h('p', {class: 'small muted'}, 'Колесо мыши — масштаб у курсора, перетаскивание — сдвиг (при «Выделении» — лассо, сдвиг — пробел+перетаскивание '
          + 'или средней кнопкой), «Вписать» — вся картинка. ', 'Ctrl+Z — отменить, Ctrl+Shift+Z — повторить, Esc — снять выделение.')),
      panel);

    // --- картинка: загрузка, раскраска, масштаб ---------------------------------------------------------------------------
    async function load() {
      const version = geometryKey(j);
      if (loadedVersion === version) return;
      loadedVersion = version;
      let next;
      try { next = await splitSvg(j); } catch (e) {
        loadedVersion = null;
        loading.hidden = false;
        loading.setAttribute('class', 'vw-ed-loading alert bad');
        return fill(loading, e.message);
      }
      if (version !== geometryKey(j)) return;                 // пока грузилось, пришёл рисунок новее: его загрузка уже идёт
      const {width: W, height: H} = j.document.size_mm;
      loadedWidth = W;
      const step = Math.max(W, H) / 80;
      missId = `vw-miss-${id}-${version}`.replace(/[^\w-]/g, '-');
      const pattern = svgEl('pattern', {id: missId, patternUnits: 'userSpaceOnUse', width: step, height: step, patternTransform: 'rotate(45)'});
      pattern.append(svgEl('rect', {width: step, height: step, fill: '#ffffff'}), svgEl('rect', {width: step / 3, height: step, fill: MISSING}));
      const defs = svgEl('defs', {});
      defs.append(pattern);
      // оригинал — в той же рамке и пропорциях, что и разбиение; грузится, только когда его показывают
      zonePics = svgEl('g', {class: 'vw-zone-pics'});
      next.prepend(defs, svgEl('image', {x: 0, y: 0, width: W, height: H, preserveAspectRatio: 'none'}), zonePics);
      next.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      paths = new Map(); colourOf = new Map(); byColour = new Map();
      for (const path of next.querySelectorAll('path[data-region]')) {
        const rid = path.getAttribute('data-region'), k = Number(path.getAttribute('data-color'));
        paths.set(rid, path);
        colourOf.set(rid, k);
        if (!byColour.has(k)) byColour.set(k, []);
        byColour.get(k).push(rid);
      }
      const group = next.querySelector('g.vw-borders');
      borders = group ? [...group.querySelectorAll('path')].map((b) => ({d: b.getAttribute('d'), sides: b.getAttribute('data-sides').split(' ')})) : [];
      if (group) group.remove();                               // kept as data only: the page does not carry them twice
      bordersOf = new Map();
      borders.forEach((b, i) => { for (const rid of b.sides) { if (!bordersOf.has(rid)) bordersOf.set(rid, []); bordersOf.get(rid).push(i); } });
      lines = svgEl('g', {class: 'vw-outlines'});
      for (const kind of ['vw-zone', 'vw-hot', 'vw-sel']) lines.append(svgEl('path', {class: `vw-outline vw-halo ${kind}`}), svgEl('path', {class: `vw-outline ${kind}`}));
      next.append(lettering.layer, lines);                    // the inscriptions over the regions, the outlines (no pointer) over all
      if (svg) svg.remove();
      stage.prepend(next);
      svg = next;
      loading.hidden = true;
      hot = [];
      state.selection = new Set([...state.selection].filter((rid) => paths.has(rid)));
      if (hover && !paths.has(hover)) hover = null;
      setBox(vb.x, vb.y, vb.w);
      paint();
      showZones();
      showImage();
      outlineSelection();
      syncSelection();
      renderLayers();
      refreshHover();
    }

    function paint() {
      if (!svg) return;
      byEntry = new Map();
      farCount = 0;
      for (const [rid, path] of paths) {
        const r = lookup(rid, colourOf.get(rid));
        let colour;
        if (state.view === 'source') colour = r.c ? rgb(r.c.srgb) : '#ffffff';
        else if (r.zone) colour = SEE_THROUGH;
        else if (r.excluded) colour = EXCLUDED;
        else if (r.missing) colour = `url(#${missId})`;
        else colour = rgb(r.entry.srgb);
        path.setAttribute('fill', colour);
        path.setAttribute('stroke', r.missing && state.view !== 'source' ? MISSING : r.zone && state.view !== 'source' ? 'none' : colour);
        if (r.entry) {
          const key = String(r.entryId);
          if (!byEntry.has(key)) byEntry.set(key, []);
          byEntry.get(key).push(rid);
        }
        setClass(path, 'vw-far', !!r.far);
        if (r.far) farCount += 1;
      }
      syncSvgClass();
      syncFarNote();
    }

    function syncSvgClass() {
      if (svg) svg.setAttribute('class', ['vw-ed-svg', state.view === 'original' ? 'view-original' : '', state.far ? 'show-far' : '',
        sideTab === 'photo' ? 'show-zones' : '', sideTab === 'texts' ? 'show-texts' : ''].filter(Boolean).join(' '));
    }

    /** The outline of a set of regions as one shape: the borders with a region of the set on one side only (none between two of them). */
    function outlineOf(ids) {
      const inside = new Set(ids), parts = new Set();
      for (const rid of inside) {
        for (const i of bordersOf.get(rid) || []) if (borders[i].sides.length < 2 || !borders[i].sides.every((s) => inside.has(s))) parts.add(i);
      }
      return [...parts].map((i) => borders[i].d).join(' ');
    }

    /** One kind of outline (``vw-sel``, ``vw-hot``, ``vw-zone``) around each of ``groups`` (lists of regions): a light line on a dark halo,
        so it shows on light and dark titanium alike; ``data-regions`` names what it outlines. */
    function drawLine(kind, groups) {
      if (!lines) return;
      const d = groups.filter((g) => g.length).map(outlineOf).join(' '), named = groups.flat().sort().join(' ');
      for (const p of [...lines.querySelectorAll(`path.${kind}`)]) {
        if (d) p.setAttribute('d', d); else p.removeAttribute('d');
        if (!p.classList.contains('vw-halo')) p.setAttribute('data-regions', named);
      }
    }

    /** Картинки фотозон — каждая на своём прямоугольнике под областями зоны; адрес меняется, только когда меняется сама картинка. */
    function showZones() {
      if (!zonePics) return;
      const shown = new Map([...zonePics.querySelectorAll('image')].map((im) => [im.getAttribute('data-zone'), im]));
      for (const z of j.zones || []) {
        if (!z.picture) continue;
        const key = String(z.number);
        const im = shown.get(key) || svgEl('image', {class: 'vw-zone-pic', 'data-zone': key, preserveAspectRatio: 'none'});
        for (const [k, v] of [['x', z.box.x], ['y', z.box.y], ['width', z.box.width], ['height', z.box.height]]) im.setAttribute(k, v);
        setPicture(im, z.picture);
        if (!shown.has(key)) zonePics.append(im);
        shown.delete(key);
      }
      for (const im of shown.values()) im.remove();
      drawLine('vw-zone', (j.zones || []).map((z) => z.regions.filter((rid) => paths.has(rid))));     // each zone one shape, shown on «Фото»
    }

    /** A zone's new picture replaces its old one only once it has loaded: the old one stays in place meanwhile, never a blank zone. */
    function setPicture(im, src) {
      if (im.getAttribute('href') === src || im.getAttribute('data-next') === src) return;
      if (!im.getAttribute('href') || typeof Image === 'undefined') return im.setAttribute('href', src);
      im.setAttribute('data-next', src);
      const next = new Image();
      next.onload = next.onerror = () => {
        if (im.getAttribute('data-next') !== src) return;                   // a newer picture was asked for meanwhile
        im.setAttribute('href', src);
        im.removeAttribute('data-next');
      };
      next.src = src;
    }

    function showImage() {
      const image = svg && svg.querySelector('image');
      if (image && state.view === 'original' && !image.getAttribute('href')) image.setAttribute('href', `/api/plans/${id}/source-image`);
    }

    function setView(v) {
      state.view = v;
      viewButtons.forEach((b, i) => b.setAttribute('aria-pressed', VIEWS[i][0] === v ? 'true' : 'false'));
      showImage();
      paint();
    }

    function setBox(x, y, w) {
      const {width: W, height: H} = j.document.size_mm;
      w = clamp(w, W / 64, W);
      const hh = w * H / W;
      vb = {x: clamp(x, Math.min(0, W - w), Math.max(0, W - w)), y: clamp(y, Math.min(0, H - hh), Math.max(0, H - hh)), w, h: hh};
      if (svg) svg.setAttribute('viewBox', [vb.x, vb.y, vb.w, vb.h].map((v) => +v.toFixed(4)).join(' '));
      fill(zoomLabel, `${Math.round(W / vb.w * 100)} %`);
      if (sideTab === 'texts') lettering.redraw();             // the handles keep their size on screen
    }

    // экранная точка → точка картинки (мм) при preserveAspectRatio «meet»
    function frame() {
      const r = stage.getBoundingClientRect();
      const s = Math.min(r.width / vb.w, r.height / vb.h) || 1;
      return {r, s, ox: (r.width - vb.w * s) / 2, oy: (r.height - vb.h * s) / 2};
    }
    function zoomAt(factor, ux, uy) {
      const W = j.document.size_mm.width;
      const w = clamp(vb.w / factor, W / 64, W), k = w / vb.w;
      setBox(ux - (ux - vb.x) * k, uy - (uy - vb.y) * k, w);
    }
    const zoomBy = (factor) => zoomAt(factor, vb.x + vb.w / 2, vb.y + vb.h / 2);
    const fit = () => setBox(0, 0, j.document.size_mm.width);

    // --- мышь: колесо — масштаб, перетаскивание дальше 4 px — сдвиг, а не щелчок ---------------------------------------------
    let drag = null, dragged = false, lettered = false;
    stage.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const f = frame();
      const delta = (ev.deltaY || 0) * (ev.deltaMode === 1 ? 16 : 1);
      zoomAt(clamp(Math.exp(-delta * 0.002), 0.5, 2), vb.x + (ev.clientX - f.r.left - f.ox) / f.s, vb.y + (ev.clientY - f.r.top - f.oy) / f.s);
    }, {passive: false});
    const toMm = (ev, f = frame()) => [vb.x + (ev.clientX - f.r.left - f.ox) / f.s, vb.y + (ev.clientY - f.r.top - f.oy) / f.s];
    stage.addEventListener('pointerdown', (ev) => {
      if (ev.button > 1) return;
      if (ev.button === 1) ev.preventDefault();               // средняя кнопка — сдвиг, а не автопрокрутка страницы
      dragged = false;
      if (ev.button === 0 && !spaceHeld && lettering.down(ev, toMm(ev))) {     // «Надписи»: надпись, её ручка или точка пути
        lettered = true;
        try { stage.setPointerCapture(ev.pointerId); } catch (_) { /* указатель уже отпущен */ }
        return;
      }
      const lasso = ev.button === 0 && state.tool === 'select' && !spaceHeld && sideTab !== 'texts';
      drag = {x: ev.clientX, y: ev.clientY, vb: {...vb}, s: frame().s, pointer: ev.pointerId, moving: false, lasso, points: [], line: null};
    });
    stage.addEventListener('pointermove', (ev) => {
      if (lettered) return lettering.move(ev, toMm(ev));
      if (drag) {
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (!drag.moving && Math.hypot(dx, dy) > 4) {
          drag.moving = true;
          try { stage.setPointerCapture(drag.pointer); } catch (_) { /* указатель уже отпущен */ }
          tip.hidden = true;
          if (drag.lasso) startLasso(ev);
          else stage.classList.add('panning');
        }
        if (drag.moving && drag.lasso) return drag.cancelled ? undefined : extendLasso(ev);
        if (drag.moving) return setBox(drag.vb.x - dx / drag.s, drag.vb.y - dy / drag.s, drag.vb.w);
      }
      if (sideTab !== 'texts') hoverAt(ev);
    });
    const endDrag = (ev) => {
      if (lettered) {
        lettered = false;
        if (lettering.up(ev, ev && ev.clientX != null ? toMm(ev) : null)) dragged = true;
        return;
      }
      if (drag && drag.moving) {
        dragged = true;
        stage.classList.remove('panning');
        if (drag.lasso && !drag.cancelled) finishLasso(drag, ev || {});
      }
      drag = null;
    };

    // --- лассо: обвести мышью области инструментом «Выделение»; выбираются те, что внутри хотя бы наполовину (решает сервер) ----------
    function startLasso(ev) {
      drag.line = svgEl('polyline', {class: 'vw-lasso', points: ''});
      if (svg) svg.append(drag.line);
      drag.points = [toMm({clientX: drag.x, clientY: drag.y})];
      drag.last = [drag.x, drag.y];
      extendLasso(ev);
    }
    function extendLasso(ev) {
      if (Math.hypot(ev.clientX - drag.last[0], ev.clientY - drag.last[1]) < LASSO_STEP) return;
      drag.last = [ev.clientX, ev.clientY];
      drag.points.push(toMm(ev));
      if (drag.line) drag.line.setAttribute('points', drag.points.map(([x, y]) => `${+x.toFixed(3)},${+y.toFixed(3)}`).join(' '));
    }
    function cancelLasso() {                                  // Escape while a lasso is drawn: it selects nothing
      if (!drag || !drag.lasso || !drag.moving) return;
      if (drag.line) drag.line.remove();
      drag.line = null;
      drag.cancelled = true;
    }
    async function finishLasso(done, ev) {
      if (done.line) done.line.remove();
      if (done.points.length < 3) return;
      const how = ev.altKey ? 'remove' : ev.shiftKey ? 'add' : 'replace';
      let got;
      try { got = await App.post(`/vector/${id}/lasso`, {points: done.points.map(([x, y]) => [+x.toFixed(3), +y.toFixed(3)])}); }
      catch (e) { return toast(e.message); }
      if (got.version !== j.document.version) return;          // пока считалось, разбиение сменилось
      const ids = got.regions.filter((rid) => paths.has(rid));
      if (how === 'replace') state.selection = new Set(ids);
      else for (const rid of ids) mark(state.selection, rid, how === 'add');
      outlineSelection();
      syncSelection();
      if (!ids.length) toast('Лассо не обвело ни одной области хотя бы наполовину');
    }
    stage.addEventListener('pointerup', endDrag);
    stage.addEventListener('pointercancel', endDrag);
    stage.addEventListener('pointerleave', () => { if (!drag) setHover(null); });
    stage.addEventListener('click', (ev) => {
      if (dragged) { dragged = false; return; }               // конец перетаскивания — не щелчок
      if (sideTab === 'texts') return lettering.click(ev, toMm(ev));      // на «Надписях» щелчок не красит области
      const path = ev.target && ev.target.closest ? ev.target.closest('path[data-region]') : null;
      if (path) clickRegion(path.getAttribute('data-region'), ev);
    });

    // --- наведение: обвести то, что изменит щелчок, и подсказка у курсора ------------------------------------------------------
    function hoverAt(ev) {
      const path = ev.target && ev.target.closest ? ev.target.closest('path[data-region]') : null;
      const rid = path ? path.getAttribute('data-region') : null;
      if (rid !== hover) setHover(rid);
      if (rid) placeTip(ev);
    }

    function setHover(rid) {
      hover = rid;
      if (!rid) { tip.hidden = true; return setHot([]); }
      setRef(colourOf.get(rid));
      if (state.tool === 'brush' && state.scope === 'fill') wantReach(rid);
      setHot(clickSet(rid));
      showTip(rid);
    }
    const refreshHover = () => (hover ? setHover(hover) : setHot([]));

    function clickSet(rid) {
      if (state.tool !== 'brush' || state.scope === 'region') return [rid];
      if (state.scope === 'colour') return byColour.get(colourOf.get(rid)) || [rid];
      const r = reach.get(reachKey(rid));
      return r && r.regions ? r.regions : [rid];
    }

    function setHot(ids) {
      hot = ids.filter((rid) => paths.has(rid));
      drawLine('vw-hot', [hot]);
    }

    // заливка: какие области она займёт, спрашивается у сервера (через 120 мс покоя, один раз на область, похожесть и версию)
    const reachKey = (rid) => `${rid}|${state.similarity}|${j.document.version}`;
    function wantReach(rid) {
      clearTimeout(reachTimer);
      if (reach.has(reachKey(rid))) return;
      reachTimer = setTimeout(async () => {
        const key = reachKey(rid);
        try { reach.set(key, await get(`/vector/${id}/reach?region=${encodeURIComponent(rid)}&similarity_de=${state.similarity}`)); }
        catch (e) { reach.set(key, {error: e.message}); }
        if (hover === rid && reachKey(rid) === key && state.tool === 'brush' && state.scope === 'fill') { setHot(clickSet(rid)); showTip(rid); }
      }, 120);
    }

    function clickText(rid) {
      if (state.tool === 'pipette') return 'Щелчок — сделать цвет титана этой области активным';
      if (state.tool === 'select') return state.selection.has(rid) ? 'Щелчок — оставить выбранной только её, Shift+щелчок — убрать из выделения'
        : 'Щелчок — выбрать, Shift+щелчок — добавить к выделению';
      const what = (state.active == null ? 'вернуть автоматический выбор' : 'покрасить активным цветом')
        + (state.scope !== 'colour' && lookup(rid, colourOf.get(rid)).zone ? ' и вывести из фотозоны' : '');
      if (state.scope === 'colour') return `Щелчок — ${what}: весь исходный цвет № ${colourOf.get(rid) + 1}, областей ${(byColour.get(colourOf.get(rid)) || []).length}`;
      if (state.scope === 'fill') {
        const r = reach.get(reachKey(rid));
        return `Щелчок — ${what}: заливка похожих (ΔE ${state.similarity}), ` + (!r ? 'считаем области…' : r.error ? r.error : `областей ${r.regions.length}`);
      }
      return `Щелчок — ${what}: только эта область`;
    }

    function showTip(rid) {
      const k = colourOf.get(rid), r = lookup(rid, k), e = r.entry;
      if (!r.c) { tip.hidden = true; return; }
      fill(tip, h('div', {}, `Область ${rid} · исходный цвет № ${k + 1} · `, r.zone ? `фотозона ${r.zone.number}: ${VectorPhoto.zoneSummary(r.zone)}` : ['титан: ',
        r.excluded ? 'исключена' : r.missing ? 'цвета больше нет среди измерений' : [chip(e.srgb, labText(e.lab)), `ΔE ${num(de(r.c.lab, e.lab))}`, r.own ? ' · свой цвет области' : null]]),
      e ? h('div', {class: 'muted'}, `рецепт: ${params(e.parameters)} · ${seconds(e.time_s_per_cm2)}`) : null,
      h('div', {class: 'vw-ed-tip-do'}, clickText(rid)));
      tip.hidden = false;
    }

    function placeTip(ev) {
      const r = stage.getBoundingClientRect();
      let x = ev.clientX - r.left + 16, y = ev.clientY - r.top + 16;
      if (x + 300 > r.width) x = Math.max(4, ev.clientX - r.left - 316);
      if (y + 110 > r.height) y = Math.max(4, ev.clientY - r.top - 120);
      tip.setAttribute('style', `left:${Math.round(x)}px;top:${Math.round(y)}px`);
    }

    // --- щелчок: кисть, пипетка (и Alt+щелчок кистью), выделение -------------------------------------------------------------
    function clickRegion(rid, ev) {
      setRef(colourOf.get(rid));
      if (state.tool === 'pipette' || (state.tool === 'brush' && ev.altKey)) return pipette(rid);
      if (state.tool === 'select') return select(rid, !!ev.shiftKey);
      const op = {op: 'paint', region: rid, scope: state.scope, entry_id: state.active};
      if (state.scope === 'fill') op.similarity_de = state.similarity;
      return act(op);
    }

    function pipette(rid) {
      const r = lookup(rid, colourOf.get(rid));
      if (r.entry) return setActive(r.entryId);
      toast(r.zone ? `Область ${rid} в фотозоне ${r.zone.number}: она гравируется картинкой, цвета титана у неё нет`
        : r.excluded ? `Область ${rid} исключена: цвета титана у неё нет` : `У области ${rid} нет измеренного цвета титана`);
    }

    function select(rid, add) {
      if (add) mark(state.selection, rid, !state.selection.has(rid));
      else state.selection = new Set(state.selection.size === 1 && state.selection.has(rid) ? [] : [rid]);
      outlineSelection();
      syncSelection();
      if (hover) showTip(hover);
    }
    function clearSelection() { state.selection = new Set(); outlineSelection(); syncSelection(); }
    /** Escape: nothing stays outlined on the picture but the photo zones - the selection and a lasso being drawn go, and so does the line
        under the pointer (a region's or a zone card's) until the pointer moves again. */
    function dropSelection() {
      cancelLasso();
      hover = null;
      tip.hidden = true;
      setHot([]);
      if (state.selection.size) clearSelection();
    }
    function selectOnly(ids) {
      setTool('select');
      state.selection = new Set(ids.filter((rid) => paths.has(rid)));
      outlineSelection();
      syncSelection();
      if (sideTab !== 'photo') sideTabs.select('brush');       // the selection and its actions are on «Кисть» and on «Фото»
    }

    function outlineSelection() {
      drawLine('vw-sel', [[...state.selection].filter((rid) => paths.has(rid))]);
    }

    // --- действия: по одному, по порядку; экран обновляет run, редактор — update -----------------------------------------------
    async function act(op, after) {
      pending += 1;
      el.classList.add('busy');
      const ok = await run(op);
      pending -= 1;
      if (!pending) el.classList.remove('busy');
      if (ok && after) after();
      return ok;
    }
    function undoRedo(kind) { if ((j[kind] || 0) > 0) act({op: kind}); }

    // --- панель -----------------------------------------------------------------------------------------------------------
    function setTool(t) {
      state.tool = t;
      toolButtons.forEach((b, i) => b.setAttribute('aria-pressed', TOOLS[i][0] === t ? 'true' : 'false'));
      stage.setAttribute('class', `vw-ed-stage tool-${t}` + (spaceHeld ? ' pan-ready' : ''));
      scopeBox.hidden = t !== 'brush';
      refreshHover();
    }

    function setScope(s) {
      state.scope = s;
      scopeButtons.forEach((b, i) => b.setAttribute('aria-pressed', SCOPES[i][0] === s ? 'true' : 'false'));
      simBox.hidden = s !== 'fill';
      refreshHover();
    }

    function setSimilarity(value) {
      const v = clamp(Number(value) || SIMILARITY, 0.5, 50);
      state.similarity = v;
      simNumber.value = v; simRange.value = Math.min(v, 30);
      refreshHover();
    }

    function setActive(entryId) {
      state.active = entryId ?? null;
      syncActive();
      if (hover) showTip(hover);
    }

    // палитра стоит по ΔE к исходному цвету последней наведённой или щёлкнутой области (перестраивается через 150 мс покоя)
    function setRef(k) {
      if (k == null || k === state.ref) return;
      state.ref = k;
      clearTimeout(sortTimer);
      sortTimer = setTimeout(() => { renderPalette(); syncActive(); }, 150);
    }
    const refColour = () => (state.ref == null ? null : j.colours.find((c) => Number(c.index) === state.ref) || null);
    const activeEntry = () => (state.active == null ? null : (entries || []).find((e) => same(e.id, state.active)) || j.entries[state.active] || null);

    function syncActive() {
      const e = activeEntry(), ref = refColour();
      autoBtn.setAttribute('aria-pressed', state.active == null ? 'true' : 'false');
      fill(activeBox, e ? h('span', {class: 'vw-ed-big', style: `background:${rgb(e.srgb)}`, title: labText(e.lab)}) : h('span', {class: 'vw-ed-big auto', 'aria-hidden': 'true'}, 'А'),
        h('div', {class: 'small'}, e ? [h('div', {}, ref ? `ΔE ${num(de(e.lab, ref.lab))} до исходного цвета № ${ref.index + 1}` : 'ΔE — наведите на область', ' · ', seconds(e.time_s_per_cm2)),
          h('div', {class: 'muted'}, params(e.parameters)),
          h('div', {class: 'muted'}, [BASIS[e.basis], e.automatic === false ? 'автоматика его не выбирает' : null].filter(Boolean).join(' · ')),
          e.sources ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', originText(e.sources)) : null]
          : state.active != null ? 'Загрузка цвета…'
            : [h('strong', {}, 'Авто'), h('div', {class: 'muted'}, 'Щелчок кистью возвращает областям автоматический выбор цвета. Выберите цвет в палитре или пипеткой.')]));
      for (const b of grid.querySelectorAll('button')) {
        const on = same(b.getAttribute('data-entry'), state.active);
        setClass(b, 'picked', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }

    async function loadPalette() {
      const key = `${j.id}:${JSON.stringify(j.settings)}`;
      if (key === paletteKey) return renderPalette();
      paletteKey = key;
      paletteError = null;
      if (!entries) renderPalette();
      try { const list = await palette(j); if (key === paletteKey) entries = list; } catch (e) { if (key === paletteKey) { entries = null; paletteError = e.message; } }
      if (key === paletteKey) { renderPalette(); syncActive(); }
    }

    function renderPalette() {
      const ref = refColour();
      fill(paletteHead, entries ? `Палитра: ${entries.length}` : 'Палитра');
      fill(paletteNote, 'Все измеренные цвета этого лазера, линзы и титана этой марки (с любой плиты). ',
        ref ? `Ближайшие к исходному цвету № ${ref.index + 1} — первыми. ` : 'Наведите на область — ближайшие к её исходному цвету встанут первыми. ',
        'Пунктир — сняты без привязки к эталону, точка — автоматика их не берёт.');
      fill(paletteFoot);
      if (!entries) return fill(grid, h('p', {class: paletteError ? 'alert bad' : 'muted small'}, paletteError || 'Загрузка палитры…'));
      const d = (e) => (ref ? de(e.lab, ref.lab) : null);
      const sorted = [...entries].sort(ref ? (a, b) => d(a) - d(b) : (a, b) => b.lab[0] - a.lab[0]);
      // the nearest first, a page at a time (DEC-090): hundreds of squares are not scrolled through; the chosen colour stays in view
      const shown = sorted.slice(0, paletteShown);
      const chosen = sorted.find((e) => same(e.id, state.active));
      if (chosen && !shown.includes(chosen)) shown.push(chosen);
      const rest = sorted.length - Math.min(paletteShown, sorted.length);
      if (rest > 0) {
        fill(paletteFoot, h('span', {class: 'muted small'}, `показано ${Math.min(paletteShown, sorted.length)} из ${sorted.length}`),
          btn(`Показать ещё ${Math.min(PALETTE_PAGE, rest)}`, () => { paletteShown += PALETTE_PAGE; renderPalette(); syncActive(); }, 'btn-small'));
      }
      fill(grid, shown.map((e) => {
        const title = [d(e) == null ? null : `ΔE ${num(d(e))}`, seconds(e.time_s_per_cm2), e.basis === 'as-shot' ? 'снят без привязки' : null,
          e.automatic ? null : 'автоматика не берёт', e.sources ? `${STEADY[steadiness(e)][0]}; ${originText(e.sources)}` : null].filter(Boolean).join(' · ');
        return h('button', {type: 'button', class: `vw-swatch steady-${steadiness(e)}` + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (same(e.id, state.active) ? ' picked' : ''),
          style: `background:${rgb(e.srgb)}`, 'data-entry': e.id, title, 'aria-label': title, 'aria-pressed': same(e.id, state.active) ? 'true' : 'false',
          onClick: () => setActive(e.id)});
      }));
    }

    /** Соседи по границе в текущей версии разбиения: один запрос на версию; пока он идёт, соседей не знаем (угол — не граница). */
    async function loadNear() {
      const key = `${id}:${j.document.version}`;
      if (key === nearKey) return;
      nearKey = key; near = null; nearFailed = false;
      syncSelection();
      let got = null, failed = false;
      try { got = (await neighbours(j)).neighbours; } catch (e) { failed = true; }
      if (key !== nearKey) return;                            // пока грузилось, версия сменилась
      near = got; nearFailed = failed;
      syncSelection();
    }

    /** Связно ли выделение общими границами: true или false; null, пока соседей не знаем. */
    function connected(ids) {
      if (!near) return null;
      const wanted = new Set(ids), seen = new Set([ids[0]]), queue = [ids[0]];
      while (queue.length) {
        for (const other of near[queue.pop()] || []) {
          if (wanted.has(other) && !seen.has(other)) { seen.add(other); queue.push(other); }
        }
      }
      return seen.size === wanted.size;
    }

    /** The selection's source colour for choosing: the mean Lab of the selected regions' source colours (the window lists the nearest first). */
    function selectionLab(ids) {
      const labs = ids.map((rid) => (lookup(rid, colourOf.get(rid)).c || {}).lab).filter(Boolean);
      return labs.length ? [0, 1, 2].map((i) => labs.reduce((t, l) => t + l[i], 0) / labs.length) : [50, 0, 0];
    }
    /** The titanium colour all selected regions share, or null: the window marks it as the current one. */
    function commonEntry(ids) {
      const found = new Set(ids.map((rid) => lookup(rid, colourOf.get(rid)).entryId || null));
      return found.size === 1 ? [...found][0] : null;
    }

    /** One selected region split again into finer regions by colour (work-size-and-splitting-a-region-again, REQ-002): the window asks
        into how many colours; the largest part keeps the region's id and colour, the others take the nearest titanium colours. */
    function splitFiner(rid) {
      const count = h('input', {type: 'number', min: '2', max: '8', step: '1', value: '3', 'aria-label': 'Число цветов'});
      const box = App.modal('Разбить область мельче', h('div', {class: 'stack'},
        h('p', {class: 'small muted'}, 'Картинка внутри области делится на столько цветов, сколько указано, самой мелкой сеткой; каждый связный кусок '
          + 'становится своей областью. Внешняя граница и соседи остаются как были. Самый большой кусок сохраняет номер области, куски его '
          + 'цвета — цвет области; каждый другой цвет становится новым цветом палитры с ближайшим цветом титана. Шаг можно отменить (Ctrl+Z).'),
        App.field('Число цветов (2–8)', count)), [
        {label: 'Отмена', run: (m) => m.close()},
        {label: 'Разбить', cls: 'primary', run: async (m) => {
          const n = Math.round(parseFloat(count.value));
          if (!(n >= 2 && n <= 8)) throw new Error('Число цветов — целое от 2 до 8');
          const before = j.document.regions;
          const ok = await act({op: 'split_region', region: rid, colours: n});
          if (ok) { toast(`Область разбита на ${App.plural(j.document.regions - before + 1, ['часть', 'части', 'частей'])}`, 'ok'); m.close(); }
        }}]);
      if (count.select) count.select();
      return box;
    }

    function syncSelection() {
      const ids = [...state.selection];
      const link = ids.length > 1 ? connected(ids) : null;
      const checking = ids.length > 1 && link === null && !nearFailed;      // слияние предлагается только связному выделению (DEC-080)
      const why = link === false ? 'Слить нельзя: выбранные области не связаны общими границами (касания углом недостаточно).'
        : checking ? 'Проверяем, какие области соседние…'
          : ids.length > 1 && nearFailed ? 'Не удалось проверить, какие области соседние: слияние проверит сервер.' : null;
      const zones = j.zones || [];
      const zoned = ids.filter((rid) => lookup(rid, colourOf.get(rid)).zone);
      fill(selectionBox, h('h4', {}, 'Выделение'),
        ids.length ? h('p', {class: 'small'}, `Выбрано областей: ${ids.length}` + (zoned.length ? `, из них в фотозонах: ${zoned.length}` : ''))
          : h('p', {class: 'small muted'}, 'Инструмент «Выделение»: щелчок выбирает область, Shift+щелчок добавляет или убирает, обвести мышью — лассо '
            + '(с Shift добавляет, с Alt убирает), Esc снимает выделение.'),
        ids.length ? h('div', {class: 'row'},
          tools.pick ? btn('Цвет выделенному…', () => tools.pick(j, `Цвет титана для выделенных областей (${ids.length})`, selectionLab(ids), commonEntry(ids),
            (entryId) => act({op: 'paint', scope: 'region', regions: ids, entry_id: entryId})), 'primary') : null,
          btn('Слить в один контур', () => act({op: 'merge_regions', regions: ids}), '', ids.length < 2 || link === false || checking),
          btn('Разбить мельче…', () => splitFiner(ids[0]), '', ids.length !== 1),
          btn('Не гравировать', () => act({op: 'exclude_region', regions: ids})), btn('Гравировать', () => act({op: 'include_region', regions: ids})),
          btn('Снять выделение', clearSelection)) : null,
        ids.length ? h('div', {class: 'row vw-ed-photo-acts'},
          btn('Сделать фотозоной', () => act({op: 'photo_add', regions: ids}, () => sideTabs.select('photo')), 'primary'),
          zones.map((z) => btn(`Добавить в фотозону ${z.number}`, () => act({op: 'photo_add', regions: ids, zone: z.number}))),
          zoned.length ? btn('Вернуть в цвета', () => act({op: 'photo_remove', regions: zoned})) : null) : null,
        ids.length && !zones.length ? h('p', {class: 'small muted'}, '«Сделать фотозоной» — выделенные области выйдут фотогравировкой картинки работы, '
          + 'а не цветами; вид и шкала — во вкладке «Фото».') : null,
        ids.length === 1 ? h('p', {class: 'small muted'}, 'Слить в один контур можно две области или больше, соседние по границе. «Разбить мельче…» делит выбранную область на части по цвету.') : null,
        why ? h('p', {class: 'small muted'}, why) : null);
    }

    function syncTotals() {
      const t = j.totals || {};
      const zones = (j.zones || []).length;
      fill(totals, `Слоёв ${(t.recipes ?? (j.layers || []).length) + zones} из ${j.layer_cap}` + (zones ? ` (фотозон ${zones})` : '')
        + ` · время слоёв цвета ${duration(t.seconds)} · средний ΔE ${num(t.mean_delta_e)}`,
        t.colours ? ` · цветов в допуске ${t.within_tolerance} из ${t.colours}` : null);
      undoBtn.disabled = !(j.undo > 0);
      redoBtn.disabled = !(j.redo > 0);
      undoBtn.setAttribute('title', `Отменить (Ctrl+Z); шагов: ${j.undo || 0}`);
      redoBtn.setAttribute('title', `Повторить (Ctrl+Shift+Z); шагов: ${j.redo || 0}`);
    }

    /** While the pointer is over a line of ``list``, the regions ``regionsOf(its key)`` are outlined on the picture (the list draws its lines
        anew, so the list itself listens). */
    function outlineRows(list, regionsOf) {
      let over = null;
      list.el.addEventListener('mouseover', (ev) => {
        const line = ev.target && ev.target.closest ? ev.target.closest('.lst-row') : null;
        const key = line ? line.getAttribute('data-key') : null;
        if (key === over) return;
        over = key;
        if (key == null) refreshHover(); else setHot(regionsOf(key));
      });
      list.el.addEventListener('mouseleave', () => { over = null; refreshHover(); });
    }

    /** The colour layers, then the photo zones, as the lines of the layers' list: what each sorts and is searched by. */
    function layerItems() {
      const layers = j.layers || [];
      const regionsOf = (l) => (Array.isArray(l.regions) ? l.regions : byEntry.get(String(l.entry_id)) || []);
      const items = [...layers.map((l, pos) => {
        const e = j.entries[l.entry_id] || l, rate = e.time_s_per_cm2 ?? l.time_s_per_cm2;
        const name = l.index != null ? `C${String(l.index).padStart(2, '0')}` : '';
        return {key: 'layer:' + l.entry_id, pos, layer: l, regions: () => regionsOf(l), area: l.area_mm2,
          seconds: rate == null || l.area_mm2 == null ? null : rate * l.area_mm2 / 100, search: `${name} ${l.name || ''}`};
      }), ...(j.zones || []).map((z, i) => ({key: 'zone:' + z.number, pos: layers.length + i, zone: z, regions: () => z.regions, area: z.area_mm2,
        seconds: null, search: `Фотозона ${z.number} ${VectorPhoto.zoneSummary(z)}`}))];
      layerRegions = new Map(items.map((x) => [x.key, x.regions]));
      return items;
    }

    /** A layer on one line: the box that marks it for a merge, its colour (a press makes it the active colour), C01, the length of its rows,
        then its area, regions, inscriptions and time; a photo zone: its picture, its number, kind, area and regions. */
    function layerRow(x) {
      if (x.zone) {
        const z = x.zone;
        return [z.picture ? h('img', {class: 'vw-ed-zone-chip', src: z.picture, alt: ''}) : h('span', {class: 'sw'}),
          h('strong', {}, `Фотозона ${z.number}`), h('span', {class: 'lst-text muted'}, `${VectorPhoto.zoneSummary(z)} · ${area(z.area_mm2)} · областей ${z.regions.length}`)];
      }
      const l = x.layer, key = String(l.entry_id), e = j.entries[l.entry_id] || l;
      const count = Array.isArray(l.regions) ? l.regions.length : (l.region_count ?? x.regions().length);
      return [inRow(h('input', {type: 'checkbox', checked: state.layers.has(key), 'aria-label': `Отметить слой ${l.name || key}`,
          onChange: (ev) => { mark(state.layers, key, ev.target.checked); syncLayerMerge(); }})),
        inRow(h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(l.srgb || e.srgb)}`, title: 'Сделать активным цветом',
          'aria-label': `Сделать активным цвет слоя ${l.name || key}`, onClick: () => setActive(l.entry_id)})),
        l.index != null ? h('strong', {}, `C${String(l.index).padStart(2, '0')}`) : null,
        sizeNote(l.size),
        h('span', {class: 'lst-text muted'}, `${area(l.area_mm2)} · областей ${count}` + ((l.texts || []).length ? ` · надписей ${l.texts.length}` : '')
          + ` · ${x.seconds == null ? 'время не оценено' : duration(x.seconds)}`)];
    }

    /** What a layer's line opens: the layer's name in the file, its recipe, the length of its rows and where its colour is known from. */
    function layerDetails(x) {
      if (x.zone) {
        return h('p', {class: 'small muted'}, `Фотозона ${x.zone.number}: ${VectorPhoto.zoneSummary(x.zone)}. Вид, шкала и мощности — во вкладке «Фото».`);
      }
      const l = x.layer, e = j.entries[l.entry_id] || null, says = sizeSays(l.size);
      return h('div', {class: 'stack small'}, l.name ? h('div', {}, l.name) : null,
        e && e.parameters ? h('div', {class: 'muted'}, `рецепт: ${params(e.parameters)}`) : null,
        says ? h('div', {class: l.size.how === 'measured' ? 'muted' : 'vw-bad'}, says) : null,
        e && e.sources ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', `${originText(e.sources)} · ${App.agreed(e.agreement)}`) : null);
    }

    function renderLayers() {
      const layers = j.layers || [];
      layerList.items = layerItems();
      layerList.refresh();
      const away = layers.filter((l) => l.size && l.size.how !== 'measured').length;
      fill(layersAbout, away ? h('details', {class: 'small alert warn'},
        h('summary', {}, `${away} из ${layers.length} слоёв: цвет при длине их строк (↔) не измерен`), h('p', {}, SIZE_ABOUT)) : null);
      syncLayerMerge();
    }

    function syncLayerMerge() {
      const chosen = (j.layers || []).filter((l) => state.layers.has(String(l.entry_id)));
      if (chosen.length < 2) return fill(layerMerge, h('p', {class: 'small muted'}, 'Отметьте два слоя или больше, чтобы слить их в один цвет титана.'));
      const biggest = chosen.reduce((a, b) => ((b.area_mm2 || 0) > (a.area_mm2 || 0) ? b : a));
      const target = h('select', {'aria-label': 'Каким цветом титана станут отмеченные слои'}, chosen.map((l) => h('option',
        {value: String(l.entry_id), selected: l === biggest}, [l.index != null ? `C${String(l.index).padStart(2, '0')}` : `№ ${l.entry_id}`, area(l.area_mm2)].join(' · '))));
      fill(layerMerge, h('div', {class: 'vw-ed-merge'}, h('span', {class: 'small'}, 'Оставить цвет:'), target,
        btn('Слить в один', () => act({op: 'merge_titanium', entries: chosen.map((l) => l.entry_id), into: chosen.find((l) => String(l.entry_id) === target.value).entry_id},
          () => { state.layers = new Set(); renderLayers(); }), 'primary')));
    }

    /** A source colour on one line: the box that marks it for a merge, the colour (a press puts the palette in order by it), the titanium
        colour it is engraved with, its number, ΔE, whether it is beyond the tolerance or chosen by hand, and its regions. */
    function colourRow(c) {
      const k = Number(c.index), e = c.entry_id == null ? null : j.entries[c.entry_id];
      const excluded = c.status === 'excluded', byHand = c.status === 'hand' || c.status === 'accepted';
      return [inRow(h('input', {type: 'checkbox', checked: state.colours.has(k), 'aria-label': `Отметить исходный цвет № ${k + 1}`,
          onChange: (ev) => { mark(state.colours, k, ev.target.checked); syncColourMerge(); }})),
        inRow(h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(c.srgb)}`, title: `${labText(c.lab)} · палитра — по этому цвету`,
          'aria-label': `Исходный цвет № ${k + 1}: поставить палитру по нему`, onClick: () => setRef(k)})),
        '→', e ? chip(e.srgb, labText(e.lab)) : h('span', {class: 'muted'}, excluded ? 'не гравируется' : 'нет цвета'),
        h('strong', {}, `№ ${k + 1}`),
        c.delta_e == null ? null : h('span', {}, `ΔE ${num(c.delta_e)}`),
        c.outside_tolerance ? pill('вне допуска', 'bad') : null,
        byHand ? pill('вручную') : c.status === 'missing' ? pill('цвета титана больше нет', 'bad') : null,
        h('span', {class: 'lst-text muted'}, `областей ${c.regions}`)];
    }

    /** The action of a source colour's line: another titanium colour, or for a colour left out, engrave it again. */
    function colourActions(c) {
      const k = Number(c.index);
      if (c.status === 'excluded') return [titled(btn('Гравировать', () => act({op: 'include_colour', colour: k})), 'Вернуть области этого цвета в файл')];
      return tools.pick ? [titled(btn('Заменить', () => tools.pick(j, `Цвет группы № ${k + 1}`, c.lab, c.entry_id, (entryId) => act({op: 'set_colour', colour: k, entry_id: entryId}))),
        'Выбрать другой цвет титана: видно, откуда он известен и насколько стабилен')] : [];
    }

    /** What a source colour's line opens: where its titanium colour is known from and its recipe; the choice back to the automatic one and
        leaving the colour out of the file. */
    function colourDetails(c) {
      const k = Number(c.index), e = c.entry_id == null ? null : j.entries[c.entry_id];
      const excluded = c.status === 'excluded', byHand = c.status === 'hand' || c.status === 'accepted';
      return h('div', {class: 'stack small'},
        h('div', {class: 'muted'}, `Исходный цвет № ${k + 1}: ${labText(c.lab)} · областей ${c.regions}`),
        e && !excluded ? h('div', {class: 'muted'}, pill(...STEADY[steadiness(e)]), ' ', `${originText(e.sources)} · ${App.agreed(e.agreement)}`) : null,
        e && !excluded && e.parameters ? h('div', {class: 'muted'}, `рецепт: ${params(e.parameters)}`) : null,
        byHand || !excluded ? h('div', {class: 'row'},
          byHand ? titled(btn('Автоматически', () => act({op: 'set_colour', colour: k, entry_id: null})), 'Вернуть выбор цвета автоматике') : null,
          excluded ? null : titled(btn('Не гравировать', () => act({op: 'exclude_colour', colour: k})), 'Все области этого цвета не попадут в файл: останется только чистка'))
          : null);
    }

    function renderColours() {
      colourList.items = j.colours;
      colourList.refresh();
      syncColourMerge();
    }

    function syncColourMerge() {
      const chosen = j.colours.map((c) => Number(c.index)).filter((k) => state.colours.has(k));
      fill(colourMerge, chosen.length < 2 ? h('p', {class: 'small muted'}, 'Отметьте два исходных цвета или больше, чтобы объединить их в один.')
        : h('div', {class: 'vw-ed-merge'}, btn('Объединить исходные цвета', () => act({op: 'merge_colours', colours: chosen},
          () => { state.colours = new Set(); renderColours(); }), 'primary'), h('span', {class: 'small muted'}, `отмечено: ${chosen.length}`)));
    }

    function syncFarNote() {
      const o = j.outside, tol = j.settings.tolerance_de;
      const limit = tol == null ? 'допуска ΔE' : `допуска ΔE ${tol}`;
      fill(farNote, o && o.colours ? `Дальше ${limit}: цветов ${o.colours}, областей ${o.regions} (${num(o.share * 100, 1)} % площади). Файл они не блокируют.`
        : farCount ? `Областей дальше ${limit}: ${farCount}. Файл они не блокируют.` : `Все цвета в пределах ${limit}.`);
    }

    function syncPanel() {
      syncTotals();
      syncSelection();
      syncActive();
      loadPalette();
      renderLayers();
      renderColours();
      syncFarNote();
    }

    /** Новое состояние работы после действия: перекрасить на месте или, если сменилась версия разбиения, загрузить её. */
    function update(next) {
      j = next;
      lookup = resolver(j);
      reach.clear();
      const known = new Set(j.colours.map((c) => Number(c.index)));
      if (state.ref != null && !known.has(state.ref)) state.ref = null;
      state.colours = new Set([...state.colours].filter((k) => known.has(k)));
      const inUse = new Set((j.layers || []).map((l) => String(l.entry_id)));
      state.layers = new Set([...state.layers].filter((e) => inUse.has(e)));
      if (loadedVersion !== geometryKey(j)) {
        const resized = loadedWidth !== null && Math.abs(loadedWidth - j.document.size_mm.width) > 1e-6;   // the work's size changed (REQ-001)
        load().then(() => { if (resized && loadedVersion === geometryKey(j)) fit(); });
      } else { paint(); showZones(); refreshHover(); }
      loadNear();
      syncPanel();
      photo.update(j);
      lettering.update(j);
    }

    const editor = {el, update, key(ev) {
      if (!el.isConnected) { if (current === editor) current = null; return; }
      if (document.querySelector('.modal-bg')) return;
      if (ev.key === 'Escape') return sideTab === 'texts' && lettering.escape() ? undefined : dropSelection();   // in a field too: Escape means nothing there
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // в поле ввода клавиши — его
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); undoRedo(z && !ev.shiftKey ? 'undo' : 'redo'); }
      else if (ev.code === 'Space' && !ev.repeat) { ev.preventDefault(); spaceHeld = true; stage.classList.add('pan-ready'); }
      else if (ev.code === 'Space') ev.preventDefault();
    }, keyup(ev) {
      if (ev.code === 'Space') { spaceHeld = false; stage.classList.remove('pan-ready'); }
    }};
    current = editor;

    setTool(sideTab === 'photo' ? 'select' : state.tool);
    ready = true;
    setScope(state.scope);
    setView(state.view);
    fit();
    load();
    loadNear();
    syncPanel();
    return editor;
  }

  return {create, splitSvg, palette, rgb, chip, params, seconds, de, duration, area, BASIS, COLOUR_FILTER, COLOUR_SORTS, inRow};
})();
