/* Путь файла работы (feature ux-engraving-lifecycle-p0): «Подготовлено → Файл получен → Результат добавлен → Проверено», готовность файла
   и одно действие «Скачать LightBurn» для любой работы и любого эксперимента; прежние файлы и полный рецепт — под раскрытием.
   Всё берётся из ответа сервера (``lifecycle`` в ответе работы, плана, ``/plans/<id>/lifecycle``): экран ничего не выводит сам.
   Файл скачивается на этот компьютер и никогда не уходит в лазер. Ошибки показываются по-русски рядом с кнопкой, повторное нажатие
   во время скачивания игнорируется. Сводка принятого результата и ``returnToWork`` возвращают оператора в работу, к которой он относится. */
'use strict';
const Lifecycle = (() => {
  const {h, fill, btn, link, pill, num, duration} = App;           // toast, fail and go are read when called: this file loads before the router's
  const STAGES = [['prepared', 'Подготовлено'], ['file', 'Файл получен'], ['result', 'Результат добавлен'], ['verified', 'Проверено']];
  const STAGE_NAME = Object.fromEntries(STAGES);
  const STATE_WORD = {done: 'выполнено', current: 'сейчас', todo: 'впереди'};
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const mm = (size) => (size ? `${num(size.width, 1)} × ${num(size.height, 1)} мм` : null);

  /** Скачивает файл через fetch и отдаёт его браузеру как загрузку; ошибка сервера становится понятным русским сообщением, на адрес API
      экран никогда не переходит. ``path`` без префикса /api. */
  async function download(path, fallbackName) {
    let res;
    try { res = await fetch('/api' + path); } catch (_) { throw new Error('Нет связи с локальным сервисом. Запущено ли приложение?'); }
    if (!res.ok) {
      let raw = null;
      try { const d = await res.json(); raw = (d.detail || d).error; } catch (_) { raw = null; }
      throw new Error(raw ? I18N.tr(raw) : `Ошибка сервера (${res.status}). Файл не получен.`);
    }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || fallbackName);
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  /** Кнопка скачивания: одно нажатие за раз (пока файл готовится, повторное нажатие ничего не делает), ошибка остаётся на экране рядом
      с кнопкой и в уведомлении, кнопка снова нажимается. ``onDone`` вызывается после удачного скачивания. */
  function downloadButton(path, name, label, {onDone = null, disabled = false, cls = '', note = null} = {}) {
    const failure = h('div', {class: 'alert bad small', role: 'alert', hidden: true});
    let busy = false;
    const key = `lc:${path}:${label}`;
    const button = btn(label, save, cls, disabled);
    button.setAttribute('data-lc-key', key);
    /** The keyboard goes back to the button it was on: the card is drawn again after a download (``onDone``), and a disabled button gives
        the focus up while the file is made. The new button when there is one, the card's heading when the button is gone or off. */
    function keepKeyboard() {
      const again = [...document.body.querySelectorAll('[data-lc-key]')].find((e) => e.getAttribute('data-lc-key') === key && !e.disabled);
      if (again) { again.focus(); return; }
      const card = document.body.querySelector('.lc-export'), heading = card && card.querySelector('h4');
      if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus(); }
    }
    async function save() {
      if (busy) return;
      const had = document.activeElement === button;
      busy = true; button.disabled = true; button.setAttribute('aria-busy', 'true'); failure.hidden = true;
      try {
        await download(path, name);
        if (note) App.toast(note, 'ok');
        if (onDone) await onDone();
      } catch (e) {
        App.fail(e);
        fill(failure, `Файл не получен: ${e.message}`, ' ', btn('Повторить', save, 'btn-small'));
        failure.hidden = false;
      } finally { busy = false; button.disabled = disabled; button.removeAttribute('aria-busy'); if (had) keepKeyboard(); }
    }
    return {el: h('span', {class: 'lc-download'}, button, failure), button, failure};
  }

  // -- the chain ------------------------------------------------------------------------------------------------------------------------
  /** Четыре шага пути файла; текущий отмечен ``aria-current="step"``, а состояние каждого сказано словом, не только цветом. Под ними —
      что дальше и действие текущего этапа. ``lc`` — ответ сервера; без него (работа ещё не загружена) ничего не рисуется.
      Результат добавляют и принимают на экране фотографий, поэтому эти два действия — переходы; остальные (к файлу, что исправить,
      сравнить) относятся к месту, где стоит экран, и ``onAction(next)`` решает, куда он переводит; без него нужное действие — только
      переход, а у «скачать» кнопка уже рядом. */
  function chain(lc, {id = 'lc-chain', onAction = null} = {}) {
    if (!lc) return null;
    const c = lc.chain;
    const items = c.steps.map((s, i) => h('li', {class: `lc-step lc-${s.state}`, 'aria-current': s.state === 'current' ? 'step' : null},
      h('span', {class: 'lc-mark', 'aria-hidden': 'true'}, s.state === 'done' ? '✓' : String(i + 1)), h('span', {class: 'lc-name'}, STAGE_NAME[s.id]),
      h('span', {class: 'lc-word'}, ` (${STATE_WORD[s.state]})`)));
    const hint = nextText(lc), act = action(lc, onAction);
    return h('div', {class: 'lc', id}, h('ol', {class: 'lc-chain', 'aria-label': 'Путь файла работы'}, items),
      hint ? h('p', {class: 'lc-next small'}, h('span', {class: 'lc-hint'}, hint), act ? [' ', act] : null) : act);
  }

  const ACTION_LABEL = {download: 'К файлу', fix: 'Что исправить', compare: 'Сравнить с ожиданием'};
  /** Действие текущего этапа: ссылка на добавление или проверку результата либо кнопка, которую оживляет экран. */
  function action(lc, onAction) {
    const a = lc.chain.next;
    if (a.code === 'add_result') return link(`/ingest?plan=${lc.plan_id}`, 'Добавить результат');
    if (a.code === 'check_result') return link(`/ingest?pair=${a.pair_id}`, 'Проверить и принять результат');
    if (!onAction) return a.code === 'compare' ? link(`/analysis/${a.pair_id}`, 'Открыть разбор') : null;
    return btn(ACTION_LABEL[a.code], () => onAction(a), 'btn-small');
  }

  /** Что сделать дальше, по состоянию работы: словами и без слов-кодов. */
  function nextText(lc) {
    const c = lc.chain, a = c.next;
    const lead = c.edited_after != null ? `Работа изменена после файла ${fileLabel(c.edited_after)}: прежний файл остаётся в истории, для этой версии нужен новый. ` : '';
    const loose = c.unlinked ? ` Результатов без файла: ${c.unlinked}: их сфотографировали раньше, чем появилась запись о файле.` : '';
    if (a.code === 'download') return lead + 'Скачайте файл и откройте его в LightBurn.' + loose;
    if (a.code === 'fix') return lead + 'Файл пока нельзя создать: ниже сказано, что исправить.' + loose;
    if (a.code === 'add_result') return `Файл ${fileLabel(c.file)} получен. После гравировки добавьте результат: файл и фотографию.` + loose;
    if (a.code === 'check_result') return 'Результат добавлен, но не принят: проверьте измерения и примите их.' + loose;
    if (a.code === 'compare') return 'Результат проверен: сравните его с ожиданием.' + loose;
    return null;
  }
  const fileLabel = (n) => (n ? `№ ${n}` : '(раньше, чем MarkView стал записывать выгрузки)');

  // -- readiness ------------------------------------------------------------------------------------------------------------------------
  /** Слова для одной причины, по которой файл пока нельзя создать. Причины приходят кодами и числами; прозы с сервера нет. */
  function blockerText(b) {
    switch (b.code) {
      case 'weak_regions': return `Областей без достаточных данных: ${b.count}. Рецепт не придумывается: удалите или исключите область, выберите настройки её группы или передайте её цвет планировщику.`;
      case 'nothing_to_engrave': return 'Гравировать нечего: все области исключены.';
      case 'too_many_layers': return `Нужно слоёв LightBurn: ${b.count}, доступно ${b.cap}. Объедините цвета или зоны.`;
      case 'no_palette': return 'Для этого лазера, линзы и титана нет измеренного цвета, которым можно залить область. Измерьте цвета или выберите другую заготовку.';
      case 'missing_colours': return `У областей (${b.count}) цвет титана больше не измерен на этом лазере, линзе и титане: выберите другой цвет.`;
      case 'text': return `Надпись ${b.number} не выгравировать: ${I18N.tr(b.problem)}. Откройте её и исправьте.`;
      case 'zone': return `Фотозона ${b.number} не гравируется: ${I18N.tr(b.problem)}.`;
      case 'draft': return 'План — черновик: завершите преобразование, и экспорт станет доступен.';
      case 'closed': return 'Эта плата заменена или отменена: откройте актуальную плату исследования.';
      case 'no_layers': return 'Слоёв нет: экспорт недоступен.';
      case 'restored': return 'Это запись выполненного задания, а не новое задание: файл не выгружается.';
      default: return 'Файл пока нельзя создать.';
    }
  }
  const TARGET_LABEL = {region: 'Показать область', tab: 'Открыть вкладку «Цвета»'};
  const MISSING_DATA = ['no_palette', 'missing_colours', 'weak_regions'];

  /** Готовность файла: размер, время, число слоёв и проверки (цвета, слои, чистка), затем причины, по которым файла пока нет, каждая
      с кнопкой к месту исправления (``onTarget(blocker)`` решает экран: область в списке, вкладка «Цвета») и ссылкой к недостающим
      измерениям (``designer``). */
  function readiness(lc, {onTarget = null, designer = null} = {}) {
    const r = lc.readiness;
    const time = r.seconds == null ? 'время не оценить' : `≈ ${duration(r.seconds)}${r.time_complete ? '' : ' (оценка неполная)'}`;
    const facts = [mm(r.size_mm), time, r.layers == null ? null : `слоёв ${r.layers} из ${r.layer_cap}`].filter(Boolean).join(' · ');
    const checks = [`цвета ${r.checks.colours ? 'достижимы' : 'есть недостижимые'}`, `слоёв ${r.checks.layers.used} из ${r.checks.layers.cap}`,
      r.kind === 'plain' ? null : `чистка C00 ${r.checks.cleanup ? 'есть' : 'нет'}`, `маркеры ${r.checks.markers ? 'включены' : 'выключены'}`].filter(Boolean).join(' · ');
    const rows = r.blockers.map((b) => h('li', {class: 'lc-blocker'}, h('span', {}, blockerText(b)), ' ',
      onTarget && b.target && TARGET_LABEL[b.target.kind] ? btn(TARGET_LABEL[b.target.kind], () => onTarget(b), 'btn-small') : null,
      designer && MISSING_DATA.includes(b.code) ? [' ', link(designer, 'Цели экспериментов')] : null));
    return h('div', {class: 'stack lc-ready'}, h('p', {}, h('strong', {}, 'Файл LightBurn: '), r.ready ? pill('готов к выгрузке', 'ok') : pill('пока нельзя', 'bad'), ' ', facts),
      h('p', {class: 'muted small'}, 'Проверки: ' + checks), rows.length ? h('ul', {class: 'lc-blockers alert warn', role: 'status'}, rows) : null,
      r.reason ? h('details', {class: 'small'}, h('summary', {}, 'Точная формулировка проверки'), h('p', {}, I18N.tr(r.reason))) : null);
  }

  // -- files ----------------------------------------------------------------------------------------------------------------------------
  const PROMISE = {saved: 'прогноз сохранён вместе с файлом', none: 'прогноз вместе с файлом не сохранялся'};

  /** Прежние файлы работы: номер, время, где в своём пути каждый и кто к нему привязан; «Скачать», пока сохранённый файл есть. Файл
      без записи о дате (выгружен до записей) назван прямо. */
  function files(lc, {onDone = null} = {}) {
    if (!lc.files.length) return h('p', {class: 'muted small'}, 'Файл ещё не создавали.');
    const rows = lc.files.map((f) => {
      const results = f.results.map((r) => h('li', {}, r.photo_name, ' · ', r.status === 'Accepted' ? 'принят' : 'ждёт проверки', ' · ',
        link(r.status === 'Accepted' ? `/analysis/${r.pair_id}` : `/ingest?pair=${r.pair_id}`, r.status === 'Accepted' ? 'разбор' : 'проверить и принять'),
        r.linked_by === 'time' ? h('span', {class: 'muted'}, ' · привязан по времени') : null));
      return h('li', {class: 'lc-file'}, h('div', {class: 'vw-line'}, h('span', {}, h('strong', {}, `Файл ${fileLabel(f.number)}`), f.name ? ` · ${f.name}` : '',
        h('div', {class: 'muted small'}, [f.recorded ? when(f.at) : 'дата неизвестна', f.layers == null ? null : `слоёв ${f.layers}`, f.regions == null ? null : `областей ${f.regions}`,
          f.seconds == null ? null : duration(f.seconds), PROMISE[f.promise], f.current ? 'актуален для работы' : 'работа с тех пор изменена или выгружена снова'].filter(Boolean).join(' · '))),
        h('span', {class: 'row'}, pill(STAGE_NAME[f.stage], f.stage === 'verified' ? 'ok' : ''),
          f.download_url ? downloadButton(f.download_url.replace(/^\/api/, ''), f.name, 'Скачать', {cls: 'btn-small', disabled: !f.downloadable, onDone}).el
            : h('span', {class: 'muted small'}, 'файл не хранится'))),
        results.length ? h('ul', {class: 'lc-results small'}, results) : null);
    });
    const loose = lc.unlinked.map((r) => h('li', {}, `${r.photo_name} · ${r.status === 'Accepted' ? 'принят' : 'ждёт проверки'} · сфотографирован до первой записи о файле `,
      link(r.status === 'Accepted' ? `/analysis/${r.pair_id}` : `/ingest?pair=${r.pair_id}`, r.status === 'Accepted' ? 'разбор' : 'проверить и принять')));
    return h('div', {class: 'stack'}, h('ul', {class: 'lc-files'}, rows),
      loose.length ? h('div', {}, h('h4', {}, 'Результаты без файла'), h('ul', {class: 'small'}, loose)) : null);
  }

  /** Карточка файла LightBurn: готовность, «Скачать LightBurn», что файл не уходит в лазер; под раскрытием — полный рецепт (``recipe``,
      узел экрана со слоями) и прежние файлы. ``path`` — адрес скачивания без /api, ``reload`` — обновить экран после скачивания. */
  function exportCard(lc, {path, name, reload = null, recipe = null, recipeLabel = 'Полный рецепт и слои', onTarget = null, designer = null, heading = 'Файл LightBurn',
                         withChain = true} = {}) {
    const r = lc.readiness;
    const got = downloadButton(path, name, 'Скачать LightBurn', {cls: 'primary', disabled: !r.ready, onDone: reload,
      note: 'Файл создан, сохранён в работе и скачан на этот компьютер. Откройте его в LightBurn и проверьте слои'});
    return h('div', {class: 'stack lc-export'}, h('h4', {}, heading), withChain ? chain(lc) : null, readiness(lc, {onTarget, designer}),
      h('div', {class: 'row'}, got.el),
      h('p', {class: 'muted small'}, 'Файл скачивается на этот компьютер. В лазер он не отправляется: его откроете и запустите вы сами.'),
      recipe ? h('details', {class: 'vw-details'}, h('summary', {}, recipeLabel), recipe) : null,
      h('details', {class: 'vw-details'}, h('summary', {}, `Прежние файлы${lc.files.length ? ` (${lc.files.length})` : ''}`), files(lc, {onDone: reload})));
  }

  // -- the strip under a work's head ------------------------------------------------------------------------------------------------------------
  /** Одна складка для полосы под шапкой работы: путь файла, насколько можно верить прогнозу и что сказано про превью. На широком экране
      полоса раскрыта, а строка складки скрыта (как и было); на узком (до 600 px) полоса свёрнута, и в строке складки сказано, на каком шаге
      работа и что говорят прогноз и превью, так что ничто не потеряно и всё в одно нажатие. ``chain``, ``forecast``, ``preview`` — три узла,
      которые экран заполняет сам; ``sync()`` пересказывает их в строке после каждого заполнения. */
  function strip({chain, forecast, preview}, {query = '(max-width:600px)'} = {}) {
    const line = h('span', {class: 'lc-strip-line small'});
    const sum = h('summary', {class: 'lc-strip-sum'}, h('strong', {}, 'Путь файла и прогноз'), line);
    const box = h('details', {class: 'lc-strip'}, sum, chain, forecast, preview);
    const text = (root, selector) => { const e = root.querySelector(selector); return e ? e.textContent.trim() : ''; };
    const narrow = typeof matchMedia === 'function' ? matchMedia(query) : null;
    const fit = () => { box.open = !(narrow && narrow.matches); };       // wide: nothing is folded; narrow: folded until it is opened
    fit();
    if (narrow && narrow.addEventListener) narrow.addEventListener('change', fit);
    function sync() {
      const step = chain.querySelector('[aria-current]'), level = text(forecast, '.pill'), caution = preview.classList.contains('alert');
      const parts = [step ? `сейчас: ${text(step, '.lc-name')}` : '', level ? `прогноз: ${level}` : '', caution ? 'у превью есть оговорка' : ''].filter(Boolean);
      fill(line, parts.length ? parts.join(' · ') : 'нет данных о пути файла');
      if (caution || forecast.querySelector('.alert')) sum.setAttribute('data-caution', 'true'); else sum.removeAttribute('data-caution');
    }
    sync();
    return {el: box, sync};
  }

  // -- the basis of a comparison ------------------------------------------------------------------------------------------------------------
  /** С чем сравнивали гравировку, прямо и без смягчений. Реконструкцию никогда не выдают за исходное обещание файла. */
  function basisNote(basis) {
    const n = basis.export_number, date = basis.exported_at ? ` (выгружен ${when(basis.exported_at)})` : '';
    const tie = (basis.ambiguous || []).length ? ` Слои файлов ${[...basis.ambiguous, n].sort((a, b) => a - b).map((x) => '№ ' + x).join(', ')} совпадают с гравировкой одинаково; выбран файл № ${n}, самый поздний из сделанных до фотографии.` : '';
    if (basis.kind === 'saved') return `Основание: прогноз, сохранённый вместе с файлом № ${n}${date}. Это то, что обещал сам файл.${tie}`;
    if (basis.kind === 'reconstructed' && n) return `Основание: реконструкция. Вместе с файлом № ${n}${date} прогноз не сохранялся; цвета восстановлены по слоям работы, какими они записаны сейчас. Это не исходное обещание файла.`;
    if (basis.kind === 'reconstructed') return 'Основание: реконструкция. Работа ещё не выгружалась, поэтому гравировка сравнена с цветами её слоёв, какие они сейчас. Это не обещание файла.';
    return `Основание: нет. Прогноз файла${n ? ' № ' + n : ''} не сохранялся, а работу с тех пор перекрасили или разбили заново: сравнить не с чем. Ниже только цвета, которые измерила фотография.`;
  }

  // -- the return to the work -------------------------------------------------------------------------------------------------------------
  /** Сводка принятого результата для экрана работы: файл и основание, как вышло, что изменилось в текущем прогнозе работы и что дальше.
      ``onNext(code)`` — кнопка действия (экран открывает вкладку сравнения). */
  function summary(s, {onNext = null, onClose = null} = {}) {
    const res = s.result, p = s.prediction;
    const line = res.matched == null ? 'Слои не сопоставлены с файлом.' : `Сопоставлено слоёв: ${res.matched} из ${res.promised}`
      + (res.beyond_layers ? `, заметно отличаются (${res.beyond_layers})` : ', заметных отличий нет')
      + (res.mean_delta_e == null ? '' : `, средняя ΔE ${num(res.mean_delta_e, 1)}`) + '.';
    const move = !p.known ? 'Как изменился текущий прогноз работы, для этого результата не записано.'
      : p.after == null ? 'У работы нет файла, от которого считать сдвиг цветов: прогноз сравнивать не с чем.'
      : `Текущий прогноз работы: слоёв, цвет которых сдвинулся с момента файла, ${p.after.layers}`
        + (p.before == null ? '' : ` (было ${p.before.layers})`) + (p.after.proposals ? `; есть ближе по цвету замены: ${p.after.proposals}` : '') + '. Файл № ' + (s.export_number ?? '—') + ' от этого не меняется.';
    return h('section', {class: 'card stack lc-summary', role: 'status', 'aria-label': 'Итог принятого результата'}, h('h3', {}, `Результат принят: «${s.work}»`),
      h('p', {class: 'small'}, basisNote(s.basis)), h('p', {class: 'small'}, line), h('p', {class: 'small'}, move),
      onNext || onClose ? h('div', {class: 'row'}, onNext ? btn(s.next === 'replace' ? 'Посмотреть замены цветов' : 'Сравнить с ожиданием', () => onNext(s.next), 'primary') : null,
        onClose ? btn('Закрыть итог', onClose) : null) : null);
  }

  /** После принятия результата — обратно в работу, к которой он относится, с короткой сводкой. ``concluded`` — ответ принятия
      (``work_review``). Возвращает true, когда перешёл; false — результат не относится к векторной работе (экран остаётся прежним). */
  function returnToWork(concluded) {
    if (!concluded || !concluded.summary) return false;
    const s = concluded.summary;
    App.toast(`Результат принят. Возвращаемся в работу «${s.work}»: ${concluded.review.summary.beyond_layers ? 'есть заметные отличия' : 'заметных отличий нет'}`, 'ok');
    App.go(s.route);
    return true;
  }

  return {STAGES, STAGE_NAME, download, downloadButton, chain, strip, readiness, files, exportCard, basisNote, summary, returnToWork, blockerText, nextText};
})();
