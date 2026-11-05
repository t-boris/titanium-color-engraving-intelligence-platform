/* Краткая достоверность (ux-evidence-summaries-p0, REQ-001): первый уровень показывает независимые сигналы — проверен ли цвет повтором,
   откуда измерение (эталонная карта или камера) и на чём оно стоит (тесты или работы); над прогнозом стоит одна пометка применимости —
   измерено при этом размере, при другой ширине или только тестовая шкала. Её уровень считает сервер по тому, из чего построена кривая
   (applicability.py); здесь только слова. Lab, ΔE и полные источники уходят в раскрывающийся блок рядом: на экране остаётся то, по чему
   решают, а цифры — по требованию. Подписи всегда текстом, цвет только усиливает их.
   One reusable component for the colour map, the knowledge pages and every screen that draws a forecast:
     EvidenceSummary.summary(e)        a row of the independent signals of one colour or recipe (``agreement``, ``doubtful``, ``measurement``,
                                       ``referenced``, ``sources`` | ``origin`` | ``engravings``); a signal with no data is not drawn
     EvidenceSummary.applicability(a)  the label above a forecast from the server's ``applicability`` (null when the server sent none)
     EvidenceSummary.disclosure(title, content, open)  the fold that holds the figures */
'use strict';
const EvidenceSummary = (() => {
  const {h, pill, steadiness, STEADY, agreed, originText, plural} = App;
  const MEASURED = {calibrated: ['по эталонной карте', 'ok'], relative: ['относительно камеры', 'warn']};
  const mm = (v) => `${String(+(+v).toFixed(1)).replace('.', ',')} мм`;
  const mmList = (list) => (list || []).map(mm).join(' и ');

  /** The label of each level of ``applicability.level``: [text, tone, the sentence under it]. */
  const LEVEL = {
    measured_here: ['измерено при этом размере', 'ok', 'Цвета этого прогноза измерены при той же ширине строк.'],
    other_width: ['измерено при другой ширине', 'warn', 'Цвета взяты из измерений другой ширины строк: на этом размере они могут выйти другими.'],
    test_scale_only: ['только тестовая шкала', 'warn', 'Прогноз построен только по тестовым шкалам; точность цвета и контраста для фотогравировки не подтверждена.'],
    unknown: ['ширина измерений неизвестна', 'warn', 'Неизвестно, при какой ширине строк измерены цвета: файлы LightBurn этих измерений недоступны.']};

  /** The independent signals of one colour or recipe, each ``{key, text, tone, title}``; a signal the data does not carry is left out. */
  function signalsOf(e) {
    const out = [];
    const a = e.agreement;
    if (a) {
      const steady = steadiness(e);
      out.push({key: 'repeat', text: STEADY[steady][0], tone: STEADY[steady][1], title: `Совпали по цвету: ${agreed(a)}`});
    }
    if (e.measurement && MEASURED[e.measurement]) {
      out.push({key: 'source', text: MEASURED[e.measurement][0], tone: MEASURED[e.measurement][1], title: 'Откуда измерение: чем исправлен цвет на фото'});
    }
    if (e.referenced === false) out.push({key: 'reference', text: 'как снято, без привязки', tone: 'warn', title: 'Цвет не привязан к чистому титану'});
    const sources = e.sources && e.sources.length ? e.sources : e.origin ? [{origin: e.origin}] : null;
    if (sources) out.push({key: 'basis', text: originText(sources), tone: '', title: 'На чём стоит цвет: тесты и работы'});
    else if (e.engravings != null) out.push({key: 'basis', text: plural(e.engravings, ['независимая гравировка', 'независимые гравировки', 'независимых гравировок']), tone: '', title: 'На чём стоит цвет'});
    return out;
  }

  /** A row of signals: «проверен повтором · по эталонной карте · 3 гравировки: 2 теста, 1 работа». ``lead`` goes first (a swatch, a circle). */
  function summary(e, {lead = null, label = 'Краткая достоверность'} = {}) {
    const signals = signalsOf(e || {});
    if (!signals.length && !lead) return null;
    return h('div', {class: 'ev-summary', role: 'group', 'aria-label': label}, lead,
      ...signals.map((s) => h('span', {class: 'pill ev-signal ev-' + s.key + (s.tone ? ' ' + s.tone : ''), title: s.title}, s.text)));
  }

  /** The fold that holds Lab, ΔE, the confidence figures and the full sources: ``content`` is a node or a list of them; closed unless ``open``. */
  function disclosure(title, content, open = false) {
    return h('details', {class: 'ev-more', open}, h('summary', {}, title), h('div', {class: 'stack small ev-more-body'}, content));
  }

  /** What the server derived (``applicability.level`` and the numbers it came from) in words, one sentence per limit. */
  function sentences(a) {
    const size = a.size || {}, c = a.counts || null;
    const out = [];
    for (const limit of a.limits && a.limits.length ? a.limits : [a.level]) {
      if (limit === 'test_scale_only') {
        out.push(c && c.ramp_only_zones ? `${plural(c.ramp_only_zones, ['фотозона рассчитана', 'фотозоны рассчитаны', 'фотозон рассчитано'])} только по тестовым шкалам: `
          + 'измерений фотогравировки этих режимов нет, точность цвета и контраста не подтверждена.' : LEVEL.test_scale_only[2]);
      } else if (limit === 'other_width') {
        if (c) out.push(`Измерения другой ширины: ${c.estimated_layers} из ${c.layers} цветовых слоёв${c.estimated_zones ? ` и ${plural(c.estimated_zones, ['фотозона', 'фотозоны', 'фотозон'])}` : ''}. `
          + 'Точность для этой работы не проверена.');
        else if (size.how === 'between') out.push(`Ширина строк ${mm(size.row_mm)} не измерялась: цвета взяты между измерениями при ${mmList(size.from_mm)}.`);
        else if (size.how === 'outside') out.push(`Измерено при ${mmList(size.measured_mm)}, при ${mm(size.row_mm)} — нет: цвета взяты при ${mmList(size.from_mm)}, дальше их не продолжали.`);
        else out.push(LEVEL.other_width[2]);
      } else if (limit === 'unknown') out.push(LEVEL.unknown[2]);
      else if (limit === 'measured_here') out.push(c ? `Цвета ${c.layers} цветовых слоёв измерены при этом размере. Фотозоны проверяются по своим шкалам.`
        : size.from_mm && size.from_mm.length ? `Цвета измерены при ширине строк ${mm(size.from_mm[0])}.` : LEVEL.measured_here[2]);
    }
    return out;
  }

  /** The label above a forecast. ``a`` is the server's ``applicability`` of a described layer or of a whole work; nothing when it sent none. */
  function applicability(a) {
    if (!a || !LEVEL[a.level]) return null;
    const [text, tone] = LEVEL[a.level];
    const lines = sentences(a);
    const size = a.size && (a.size.measured_mm || []).length ? `Ширина строк: ${a.size.row_mm == null ? '—' : mm(a.size.row_mm)}; измерено при: ${mmList(a.size.measured_mm)}.` : null;
    return h('div', {class: 'ev-applic ev-applic-' + a.level + (tone === 'ok' ? '' : ' alert warn'), role: 'note', 'data-level': a.level},
      h('div', {class: 'row ev-applic-head'}, h('strong', {class: 'small'}, 'Прогноз:'), pill(text, tone), h('span', {class: 'small ev-applic-text'}, lines[0])),
      lines.length > 1 || size ? disclosure('На чём стоит прогноз', [...lines.slice(1).map((line) => h('p', {}, line)), size ? h('p', {class: 'muted'}, size) : null]) : null);
  }

  return {summary, signalsOf, disclosure, applicability, LEVEL};
})();
