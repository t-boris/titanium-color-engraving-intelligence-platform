/* Векторная работа из фотографии, редактор цветов (REQ-043..REQ-049, DEC-001, DEC-075..DEC-077): одна большая картинка в
   цветах титана и панель рядом (под картинкой на узком экране) — инструменты (кисть, пипетка, выделение), что меняет щелчок
   кистью, активный цвет, палитра всех измеренных цветов, слои титана, исходные цвета, итоги, отмена и повтор. Каждый
   исходный цвет раскрашен сразу; цвет дальше допуска ΔE помечается и по запросу обводится на картинке, файл он не
   блокирует. Наведение обводит ровно то, что изменит щелчок (для заливки — области, которые назвал сервер). Масштаб и сдвиг
   меняют viewBox картинки. После каждого действия сервер возвращает работу целиком, и картинка перекрашивается на месте:
   масштаб, сдвиг, инструмент, активный цвет и выделение сохраняются; новая версия разбиения загружается заново.
   Слить области в один контур можно только связному выделению: кто с кем граничит, экран спрашивает у сервера один раз на
   версию разбиения (DEC-080); сервер всё равно проверяет каждое слияние. */
'use strict';
const VectorEditor = (() => {
  const {h, fill, btn, get, pill, toast, num, labText} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const EXCLUDED = '#e6e6e6';                 // исключённое не гравируется: остаётся только чистка
  const MISSING = '#d32f2f';                  // выбранного цвета титана больше нет среди измерений: штриховка
  const BASIS = {chart: 'по карте', clean: 'по чистому титану', 'as-shot': 'как снято, без привязки'};
  const TOOLS = [['brush', 'Кисть'], ['pipette', 'Пипетка'], ['select', 'Выделение']];
  const SCOPES = [['region', 'Участок'], ['colour', 'Весь исходный цвет'], ['fill', 'Заливка похожих']];
  const VIEWS = [['titanium', 'Титан'], ['source', 'Исходные цвета'], ['original', 'Оригинал']];
  const SIMILARITY = 8;                       // ΔE заливки похожих по умолчанию
  const svgCache = new Map();
  const paletteCache = new Map();
  const nearCache = new Map();
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const chip = (c, title) => h('span', {class: 'sw', style: `background:${rgb(c)}`, title: title || ''});
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} кГц · ${num(p.speed, 0)} мм/с · Q-Pulse ${num(p.pulse_width, 0)} нс`
    + (p.line_interval == null ? '' : ` · шаг ${num(p.line_interval, 3)} мм`) + ` · ${p.passes ?? 1} проход(а)` + (p.cross_hatch ? ' · cross-hatch' : '');
  const seconds = (s) => (s == null ? 'не оценено' : num(s, 1) + ' с/см²');
  const de = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);       // CIE76, как на сервере
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
    return (rid, k) => {
      const c = colours.get(k) || null;
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

  /** Редактор работы j; run(op) отправляет одно действие и обновляет экран (возвращает true, если сервер его принял). */
  function create(j, run) {
    const id = j.id;
    const state = {tool: 'brush', scope: 'region', similarity: SIMILARITY, active: null, view: 'titanium', far: false, ref: null,
      selection: new Set(), layers: new Set(), colours: new Set()};
    let lookup = resolver(j);
    let svg = null, loadedVersion = null, missId = '';
    let paths = new Map(), colourOf = new Map(), byColour = new Map(), byEntry = new Map();
    let vb = {x: 0, y: 0, w: j.document.size_mm.width, h: j.document.size_mm.height};
    let entries = null, paletteError = null, paletteKey = null;
    let near = null, nearKey = null, nearFailed = false;     // область → соседи по границе в текущей версии разбиения (DEC-080)
    let hover = null, hot = [], shownSelection = [], farCount = 0, pending = 0;
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
    const autoBtn = btn('Авто', () => setActive(null));
    autoBtn.setAttribute('title', 'Кисть возвращает автоматический выбор цвета');
    const activeBox = h('div', {class: 'vw-ed-active'});
    const paletteHead = h('h4', {}, 'Палитра'), paletteNote = h('p', {class: 'small muted'});
    const grid = h('div', {class: 'vw-swatches vw-ed-palette', role: 'group', 'aria-label': 'Измеренные цвета титана'});
    const layersBox = h('div', {class: 'vw-ed-list vw-ed-layers'}), layerMerge = h('div', {});
    const farBox = h('input', {type: 'checkbox', onChange: (ev) => { state.far = ev.target.checked; syncSvgClass(); }});
    const farNote = h('p', {class: 'small muted'});
    const coloursBox = h('div', {class: 'vw-ed-list'}), colourMerge = h('div', {});
    // панель на три вкладки, чтобы не прокручивать: кисть и цвет, слои титана, исходные цвета (DEC-085)
    const sideTabs = App.tabs([
      ['brush', 'Кисть', h('div', {class: 'vw-ed-pane'},
        h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Инструмент'),
          h('div', {class: 'vw-ed-group', role: 'group', 'aria-label': 'Инструмент'}, toolButtons),
          h('p', {class: 'small muted'}, 'Alt+щелчок кистью — пипетка.'), scopeBox),
        selectionBox,
        h('section', {class: 'vw-ed-section'}, h('div', {class: 'row'}, h('h4', {}, 'Активный цвет'), h('span', {class: 'spacer'}), autoBtn), activeBox),
        h('section', {class: 'vw-ed-section'}, paletteHead, paletteNote, grid))],
      ['layers', 'Слои', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Слои титана'), layersBox, layerMerge))],
      ['colours', 'Цвета', h('div', {class: 'vw-ed-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Исходные цвета'),
        h('label', {class: 'row small'}, farBox, h('span', {}, 'Показать далёкие от оригинала')), farNote, coloursBox, colourMerge))]],
      {initial: 'brush', remember: 'vw.edtab', label: 'Панель редактора', prefix: 'vw-ed-tab'});
    const panel = h('aside', {class: 'vw-ed-panel', 'aria-label': 'Инструменты и цвета'}, sideTabs.list, h('div', {class: 'vw-ed-panes'}, sideTabs.panels));
    const el = h('div', {class: 'vw-editor'},
      h('div', {class: 'vw-ed-main'}, bar, totals, stage,
        h('p', {class: 'small muted'}, 'Колесо мыши — масштаб у курсора, перетаскивание — сдвиг, «Вписать» — вся картинка. ',
          'Ctrl+Z — отменить, Ctrl+Shift+Z — повторить, Esc — снять выделение.')),
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
      const step = Math.max(W, H) / 80;
      missId = `vw-miss-${id}-${version}`.replace(/[^\w-]/g, '-');
      const pattern = svgEl('pattern', {id: missId, patternUnits: 'userSpaceOnUse', width: step, height: step, patternTransform: 'rotate(45)'});
      pattern.append(svgEl('rect', {width: step, height: step, fill: '#ffffff'}), svgEl('rect', {width: step / 3, height: step, fill: MISSING}));
      const defs = svgEl('defs', {});
      defs.append(pattern);
      // оригинал — в той же рамке и пропорциях, что и разбиение; грузится, только когда его показывают
      next.prepend(defs, svgEl('image', {x: 0, y: 0, width: W, height: H, preserveAspectRatio: 'none'}));
      next.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      paths = new Map(); colourOf = new Map(); byColour = new Map();
      for (const path of next.querySelectorAll('path[data-region]')) {
        const rid = path.getAttribute('data-region'), k = Number(path.getAttribute('data-color'));
        paths.set(rid, path);
        colourOf.set(rid, k);
        if (!byColour.has(k)) byColour.set(k, []);
        byColour.get(k).push(rid);
      }
      if (svg) svg.remove();
      stage.prepend(next);
      svg = next;
      loading.hidden = true;
      hot = []; shownSelection = [];
      state.selection = new Set([...state.selection].filter((rid) => paths.has(rid)));
      if (hover && !paths.has(hover)) hover = null;
      setBox(vb.x, vb.y, vb.w);
      paint();
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
        else if (r.excluded) colour = EXCLUDED;
        else if (r.missing) colour = `url(#${missId})`;
        else colour = rgb(r.entry.srgb);
        path.setAttribute('fill', colour);
        path.setAttribute('stroke', r.missing && state.view !== 'source' ? MISSING : colour);
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
      if (svg) svg.setAttribute('class', ['vw-ed-svg', state.view === 'original' ? 'view-original' : '', state.far ? 'show-far' : ''].filter(Boolean).join(' '));
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
    let drag = null, dragged = false;
    stage.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const f = frame();
      const delta = (ev.deltaY || 0) * (ev.deltaMode === 1 ? 16 : 1);
      zoomAt(clamp(Math.exp(-delta * 0.002), 0.5, 2), vb.x + (ev.clientX - f.r.left - f.ox) / f.s, vb.y + (ev.clientY - f.r.top - f.oy) / f.s);
    }, {passive: false});
    stage.addEventListener('pointerdown', (ev) => {
      if (ev.button > 0) return;
      dragged = false;
      drag = {x: ev.clientX, y: ev.clientY, vb: {...vb}, s: frame().s, pointer: ev.pointerId, moving: false};
    });
    stage.addEventListener('pointermove', (ev) => {
      if (drag) {
        const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
        if (!drag.moving && Math.hypot(dx, dy) > 4) {
          drag.moving = true;
          try { stage.setPointerCapture(drag.pointer); } catch (_) { /* указатель уже отпущен */ }
          stage.classList.add('panning');
          tip.hidden = true;
        }
        if (drag.moving) return setBox(drag.vb.x - dx / drag.s, drag.vb.y - dy / drag.s, drag.vb.w);
      }
      hoverAt(ev);
    });
    const endDrag = () => {
      if (drag && drag.moving) { dragged = true; stage.classList.remove('panning'); }
      drag = null;
    };
    stage.addEventListener('pointerup', endDrag);
    stage.addEventListener('pointercancel', endDrag);
    stage.addEventListener('pointerleave', () => { if (!drag) setHover(null); });
    stage.addEventListener('click', (ev) => {
      if (dragged) { dragged = false; return; }               // конец перетаскивания — не щелчок
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
      for (const rid of hot) if (paths.has(rid)) paths.get(rid).classList.remove('vw-hot');
      hot = ids.filter((rid) => paths.has(rid));
      for (const rid of hot) paths.get(rid).classList.add('vw-hot');
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
      const what = state.active == null ? 'вернуть автоматический выбор' : 'покрасить активным цветом';
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
      fill(tip, h('div', {}, `Область ${rid} · исходный цвет № ${k + 1} · титан: `,
        r.excluded ? 'исключена' : r.missing ? 'цвета больше нет среди измерений' : [chip(e.srgb, labText(e.lab)), `ΔE ${num(de(r.c.lab, e.lab))}`, r.own ? ' · свой цвет области' : null]),
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
      toast(r.excluded ? `Область ${rid} исключена: цвета титана у неё нет` : `У области ${rid} нет измеренного цвета титана`);
    }

    function select(rid, add) {
      if (add) mark(state.selection, rid, !state.selection.has(rid));
      else state.selection = new Set(state.selection.size === 1 && state.selection.has(rid) ? [] : [rid]);
      outlineSelection();
      syncSelection();
      if (hover) showTip(hover);
    }
    function clearSelection() { state.selection = new Set(); outlineSelection(); syncSelection(); }

    function outlineSelection() {
      for (const rid of shownSelection) if (paths.has(rid)) paths.get(rid).classList.remove('vw-sel');
      shownSelection = [...state.selection].filter((rid) => paths.has(rid));
      for (const rid of shownSelection) paths.get(rid).classList.add('vw-sel');
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
      stage.setAttribute('class', `vw-ed-stage tool-${t}`);
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
          h('div', {class: 'muted'}, [BASIS[e.basis], e.automatic === false ? 'автоматика его не выбирает' : null].filter(Boolean).join(' · '))]
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
      fill(paletteNote, 'Все измеренные цвета этого лазера, линзы и титана. ',
        ref ? `Ближайшие к исходному цвету № ${ref.index + 1} — первыми. ` : 'Наведите на область — ближайшие к её исходному цвету встанут первыми. ',
        'Пунктир — сняты без привязки к эталону, точка — автоматика их не берёт.');
      if (!entries) return fill(grid, h('p', {class: paletteError ? 'alert bad' : 'muted small'}, paletteError || 'Загрузка палитры…'));
      const d = (e) => (ref ? de(e.lab, ref.lab) : null);
      const sorted = [...entries].sort(ref ? (a, b) => d(a) - d(b) : (a, b) => b.lab[0] - a.lab[0]);
      fill(grid, sorted.map((e) => {
        const title = [d(e) == null ? null : `ΔE ${num(d(e))}`, seconds(e.time_s_per_cm2), e.basis === 'as-shot' ? 'снят без привязки' : null,
          e.automatic ? null : 'автоматика не берёт'].filter(Boolean).join(' · ');
        return h('button', {type: 'button', class: 'vw-swatch' + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (same(e.id, state.active) ? ' picked' : ''),
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

    function syncSelection() {
      const ids = [...state.selection];
      const link = ids.length > 1 ? connected(ids) : null;
      const checking = ids.length > 1 && link === null && !nearFailed;      // слияние предлагается только связному выделению (DEC-080)
      const why = link === false ? 'Слить нельзя: выбранные области не связаны общими границами (касания углом недостаточно).'
        : checking ? 'Проверяем, какие области соседние…'
          : ids.length > 1 && nearFailed ? 'Не удалось проверить, какие области соседние: слияние проверит сервер.' : null;
      fill(selectionBox, h('h4', {}, 'Выделение'),
        ids.length ? h('p', {class: 'small'}, `Выбрано областей: ${ids.length}`)
          : h('p', {class: 'small muted'}, 'Инструмент «Выделение»: щелчок выбирает область, Shift+щелчок добавляет или убирает, Esc снимает выделение.'),
        ids.length ? h('div', {class: 'row'},
          btn('Слить в один контур', () => act({op: 'merge_regions', regions: ids}), '', ids.length < 2 || link === false || checking),
          btn('Исключить', () => act({op: 'exclude_region', regions: ids})), btn('Вернуть', () => act({op: 'include_region', regions: ids})),
          btn('Снять выделение', clearSelection)) : null,
        ids.length === 1 ? h('p', {class: 'small muted'}, 'Слить в один контур можно две области или больше, соседние по границе.') : null,
        why ? h('p', {class: 'small muted'}, why) : null);
    }

    function syncTotals() {
      const t = j.totals || {};
      fill(totals, `Слоёв ${t.recipes ?? (j.layers || []).length} из ${j.layer_cap} · время слоёв цвета ${duration(t.seconds)} · средний ΔE ${num(t.mean_delta_e)}`,
        t.colours ? ` · цветов в допуске ${t.within_tolerance} из ${t.colours}` : null);
      undoBtn.disabled = !(j.undo > 0);
      redoBtn.disabled = !(j.redo > 0);
      undoBtn.setAttribute('title', `Отменить (Ctrl+Z); шагов: ${j.undo || 0}`);
      redoBtn.setAttribute('title', `Повторить (Ctrl+Shift+Z); шагов: ${j.redo || 0}`);
    }

    function outlineOnHover(row, ids) {
      row.addEventListener('mouseenter', () => setHot(ids()));
      row.addEventListener('mouseleave', refreshHover);
      return row;
    }

    function renderLayers() {
      const layers = j.layers || [];
      const regionsOf = (l) => (Array.isArray(l.regions) ? l.regions : byEntry.get(String(l.entry_id)) || []);
      fill(layersBox, layers.length ? layers.map((l) => {
        const key = String(l.entry_id), e = j.entries[l.entry_id] || l;
        const rate = e.time_s_per_cm2 ?? l.time_s_per_cm2;
        const count = Array.isArray(l.regions) ? l.regions.length : (l.region_count ?? regionsOf(l).length);
        return outlineOnHover(h('div', {class: 'vw-ed-item'},
          h('input', {type: 'checkbox', checked: state.layers.has(key), 'aria-label': `Отметить слой ${l.name || key}`,
            onChange: (ev) => { mark(state.layers, key, ev.target.checked); syncLayerMerge(); }}),
          h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(l.srgb || e.srgb)}`, title: 'Сделать активным цветом',
            'aria-label': `Сделать активным цвет слоя ${l.name || key}`, onClick: () => setActive(l.entry_id)}),
          l.index != null ? h('strong', {}, `C${String(l.index).padStart(2, '0')}`) : null,
          h('span', {class: 'muted'}, `${area(l.area_mm2)} · областей ${count} · ${rate == null || l.area_mm2 == null ? 'время не оценено' : duration(rate * l.area_mm2 / 100)}`)),
        () => regionsOf(l));
      }) : h('p', {class: 'small muted'}, 'Слоёв цвета нет: всё исключено.'));
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

    function renderColours() {
      fill(coloursBox, j.colours.map((c) => {
        const k = Number(c.index), e = c.entry_id == null ? null : j.entries[c.entry_id];
        const excluded = c.status === 'excluded';
        return outlineOnHover(h('div', {class: 'vw-ed-item' + (excluded ? ' excluded' : '')},
          h('input', {type: 'checkbox', checked: state.colours.has(k), 'aria-label': `Отметить исходный цвет № ${k + 1}`,
            onChange: (ev) => { mark(state.colours, k, ev.target.checked); syncColourMerge(); }}),
          h('button', {type: 'button', class: 'vw-swatch', style: `background:${rgb(c.srgb)}`, title: `${labText(c.lab)} · палитра — по этому цвету`,
            'aria-label': `Исходный цвет № ${k + 1}: поставить палитру по нему`, onClick: () => setRef(k)}),
          '→', e ? chip(e.srgb, labText(e.lab)) : h('span', {class: 'muted'}, excluded ? 'исключён' : 'нет цвета'),
          h('strong', {}, `№ ${k + 1}`),
          c.delta_e == null ? null : h('span', {}, `ΔE ${num(c.delta_e)}`),
          c.outside_tolerance ? pill('вне допуска', 'bad') : null,
          c.status === 'hand' || c.status === 'accepted' ? pill('вручную') : c.status === 'missing' ? pill('цвета титана больше нет', 'bad') : null,
          h('span', {class: 'muted'}, `областей ${c.regions}`),
          h('span', {class: 'spacer'}),
          excluded ? btn('Вернуть', () => act({op: 'include_colour', colour: k})) : btn('Исключить', () => act({op: 'exclude_colour', colour: k}))),
        () => byColour.get(k) || []);
      }));
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
      if (loadedVersion !== geometryKey(j)) load();
      else { paint(); refreshHover(); }
      loadNear();
      syncPanel();
    }

    const editor = {el, update, key(ev) {
      if (!el.isConnected) { if (current === editor) current = null; return; }
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // в поле ввода клавиши — его
      if (document.querySelector('.modal-bg')) return;
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); undoRedo(z && !ev.shiftKey ? 'undo' : 'redo'); }
      else if (ev.key === 'Escape' && state.selection.size) clearSelection();
    }};
    current = editor;

    setTool(state.tool);
    setScope(state.scope);
    setView(state.view);
    fit();
    load();
    loadNear();
    syncPanel();
    return editor;
  }

  return {create, splitSvg, palette, rgb, chip, params, seconds, de, duration, area, BASIS};
})();
