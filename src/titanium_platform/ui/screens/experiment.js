/* Эксперимент как один объект (REQ-028, DEC-055): фото с наложением всегда на виду, рядом результат, плата, выводы и все проверки.
   Маршрут /experiment/:ключ, где ключ plan-<id> (плата и её проверки) или eng-<id> (готовая работа и её фото).
   Один экран без прокрутки страницы (REQ-044, DEC-080): слева фото с наложением на всю высоту, справа вкладки «Результат» (у принятой
   фотогравировки — и «Прогноз и результат», prediction-review.js), «Матрица»,
   «Проверки», «Плата», «Работа», «Выводы»; прокручивается только длинная таблица внутри своей вкладки. Открытая вкладка запоминается
   браузером (удобство одного зрителя). */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, post, del, toast, confirmBox, go, fail, num, swatch, labText} = App;
  const KIND = {'Awaiting check': ['Ожидает проверки', ''], 'Needs correction': ['Требует исправления', 'warn'],
    'Ready to accept': ['Готова к принятию', 'ok'], Accepted: ['Принята', 'ok']};
  const STATUS_KIND = {plate_ready: 'warn', needs_review: 'warn', accepted: 'ok'};
  const ALIGN = {markers: 'по маркерам', 'marker templates': 'по узорам маркеров', 'two marker + QR': 'по двум меткам и QR',
    geometry: 'по деталям рисунка', 'element anchors': 'по элементам-якорям', picture: 'по вложенной картинке',
    'single distinctive detail': 'по одной характерной детали', 'element anchor': 'по детали', manual: 'вручную по углам',
    'manual shift': 'сдвиг вручную', 'manual rotation': 'поворот вручную', 'manual transform': 'масштаб или зеркало'};
  const MEASURE = {raw_camera_relative: 'относительно камеры', reference_chart_corrected: 'по эталонной карте'};
  // a setting the file lacks and the operator supplied is shown as the operator's (REQ-016)
  const supplied = (p, k) => (p.supplied_settings || {})[k];
  const params = (p) => [p.power == null ? null : `${num(p.power, 1)}%`, p.frequency_khz == null ? null : `${num(p.frequency_khz, 0)} кГц`,
    p.speed == null ? null : `${num(p.speed, 0)} мм/с`,
    p.pulse_width != null ? `${num(p.pulse_width, 0)} нс` : supplied(p, 'pulse_width') ? `${num(supplied(p, 'pulse_width').value, 0)} нс (введено оператором)` : (p.defaulted_settings || {}).pulse_width ? `${num(p.defaulted_settings.pulse_width.value, 0)} нс (по умолчанию лазера)` : 'Q-Pulse не задан',
    p.line_interval == null ? null : `шаг ${num(p.line_interval, 4)} мм`, p.passes == null ? null : `${p.passes} проход(а)`].filter(Boolean).join(' · ');
  const when = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');

  /** Что скрывает рамка, по сторонам в мм (REQ-024, REQ-027): из записи выравнивания проверки. */
  function frameNote(check) {
    const sides = IngestReview.hiddenMargins(check.alignment);
    return sides ? h('p', {class: 'small'}, `Рамка закрывает края, мм (ориентировочно): ${sides}. Скрытое не измеряется.`) : null;
  }

  App.register({id: 'experiment', async render(ctx) {
    const key = decodeURIComponent(ctx.arg || '');
    const exp = await get('/experiments/' + encodeURIComponent(key));
    const reload = () => App.render({preserveScroll: true});
    const pairs = exp.pairs;
    const wanted = Number(ctx.query.check);
    let current = pairs.find((p) => p.id === wanted) || pairs.find((p) => p.id === exp.main_pair_id) || pairs[pairs.length - 1] || null;
    // null until the operator chooses: the corrected photograph is shown as it is, the uncorrected (dark) RAW is lifted
    const storedLift = sessionStorage.getItem('experiment-lifted');
    let lifted = storedLift === null ? null : storedLift !== '0';
    let contours = sessionStorage.getItem('experiment-contours') !== '0';

    // -- фото с наложением: первый блок страницы, показывается всегда ----------------------------------------------
    const stage = h('div', {class: 'ep-stage'});
    const caption = h('p', {class: 'muted small ep-caption'});
    const photoTools = h('div', {class: 'ep-tools'});
    const checks = h('div', {class: 'ep-checks'});
    const result = h('div', {class: 'stack'});          // the alerts and the measured layers of the shown check
    const matrixBox = h('div', {class: 'stack'});       // its parameter matrix, when it has one
    // the photograph is shown the way its colours were measured: corrected by the chart when a chart was used,
    // so that the swatches and the picture share one exposure (the RAW as shot is darker)
    const shownCorrected = (pair) => pair.measurement === 'reference_chart_corrected';
    const isLifted = (pair) => lifted === null ? !(pair && shownCorrected(pair)) : lifted;
    function url(pair) {
      const base = '/api/pairs/' + pair.id, stamp = pair.accepted_at || pair.created_at || '';
      const view = `corrected=${shownCorrected(pair)}&visibility=${isLifted(pair) ? 'lifted' : 'normal'}&full=false&t=${encodeURIComponent(stamp)}`;
      return contours && pair.alignment ? `${base}/overlay.png?${view}` : `${base}/photo.png?${view}`;
    }
    function showPhoto() {
      if (!current) {
        stage.replaceChildren(h('div', {class: 'card empty ep-nophoto'}, h('h3', {}, 'Фото ещё нет'),
          h('p', {class: 'muted'}, 'Плата готова. Выгравируйте её и добавьте фото: оно появится здесь с наложением контуров.'),
          exp.plan_id ? link('/ingest?plan=' + exp.plan_id, 'Добавить фото') : null));
        caption.textContent = '';
        return;
      }
      const img = h('img', {class: 'ep-photo', alt: `Фото «${current.photo_name}» с наложением контуров`, src: url(current)});
      img.addEventListener('error', () => {       // проверка ещё не выровняла фото: покажем снимок без контуров
        if (!img.dataset.plain) { img.dataset.plain = '1'; img.src = `/api/pairs/${current.id}/photo.png?corrected=${shownCorrected(current)}&visibility=${isLifted(current) ? 'lifted' : 'normal'}&full=false`; }
      });
      stage.replaceChildren(h('a', {href: `/api/pairs/${current.id}/overlay.png?corrected=${shownCorrected(current)}&full=true&visibility=${isLifted(current) ? 'lifted' : 'normal'}`,
        target: '_blank', rel: 'noopener', title: 'Открыть в полном размере'}, img));
      const method = current.alignment ? `Выравнивание ${ALIGN[current.alignment] || current.alignment}` : 'Фото ещё не выровнено';
      caption.textContent = `${current.photo_name} · проверка №${current.id} · ${method}`
        + (current.measurement ? ` · цвет ${MEASURE[current.measurement] || current.measurement}` : '')
        + (shownCorrected(current) ? ' · фото показано после коррекции по карте, в той же экспозиции, что и плашки' : ' · фото показано как снято');
    }
    function showTools() {
      fill(photoTools,
        btn(contours ? 'Скрыть контуры' : 'Показать контуры', () => { contours = !contours; sessionStorage.setItem('experiment-contours', contours ? '1' : '0'); refreshAll(); }, 'btn-small'),
        btn(isLifted(current) ? 'Обычная яркость' : 'Поднять яркость', () => { lifted = !isLifted(current); sessionStorage.setItem('experiment-lifted', lifted ? '1' : '0'); refreshAll(); }, 'btn-small'),
        current && current.status === 'Accepted' ? btn('Перемерить заново', async (ev) => {
          const control = ev.currentTarget; control.disabled = true; control.textContent = 'Измеряем заново…';
          try {
            const out = await post(`/pairs/${current.id}/remeasure`);
            if (out.status === 'replaced') { toast('Перемерено новыми подсчётами; прежнее измерение заменено', 'ok'); go('/experiment/' + encodeURIComponent(key) + '?check=' + out.replaced_by); return; }
            toast('Прежнее измерение оставлено: ' + I18N.tr(out.reason || ''), 'warn');
            control.disabled = false; control.textContent = 'Перемерить заново';
          } catch (error) { control.disabled = false; control.textContent = 'Перемерить заново'; fail(error); }
        }, 'btn-small') : null,
        h('details', {class: 'ep-legend small muted'}, h('summary', {}, 'Что означают линии'),
          h('p', {}, 'Зелёные линии — контуры картинки, найденные на фото; цветные — векторы LightBurn; розовые — продолжение под рамкой.')));
    }
    function showChecks() {
      checks.replaceChildren(...pairs.slice().reverse().map((p) => {
        const [label, kind] = KIND[p.status] || [p.status, ''];
        return h('div', {class: 'ep-check' + (current && p.id === current.id ? ' is-current' : '')},
          btn(`Проверка №${p.id}`, () => { current = p; refreshAll(); }, 'btn-small'),
          h('span', {class: 'ep-check-name', title: p.photo_name}, p.photo_name), pill(label, kind),
          h('span', {class: 'muted small'}, when(p.accepted_at || p.created_at)),
          h('span', {class: 'spacer'}),
          link(p.status === 'Accepted' ? `/analysis/${p.id}` : `/ingest?pair=${p.id}`, p.status === 'Accepted' ? 'Разбор' : 'Проверить и принять'),
          btn('Удалить', () => confirmBox('Удалить проверку', `Проверка №${p.id} и её измерения исчезнут из активной базы.`, 'Удалить',
            async () => { await del('/pairs/' + p.id); toast('Проверка удалена', 'ok'); reload(); }), 'btn-small danger'));
      }));
    }
    async function showResult() {
      if (!current) { result.replaceChildren(); matrixBox.replaceChildren(); return; }
      const shown = current.id;
      const pair = await get('/pairs/' + shown);
      if (!current || current.id !== shown) return;
      const check = pair.check || {};
      const layers = (check.layers || []).filter((l) => l.measured_lab);
      const ref = check.clean_reference;
      // REQ-020: у каждого слоя — его задача; у каждой метрики — способ (подсказка) и основание измерения
      // one compact card per layer (a table of five columns does not fit the side panel): colour, name and task on the first line,
      // the settings on the second, the metrics and notes below
      const rows = layers.map((l) => h('div', {class: 'ep-layer'},
        h('div', {class: 'ep-layer-top'},
          h('span', {}, l.measured_lab_against_clean
            ? [swatch(l.measured_lab_against_clean), labText(l.measured_lab_against_clean), h('span', {class: 'muted small'}, ` · как снято: ${labText(l.measured_lab)}`)]
            : [swatch(l.measured_lab), labText(l.measured_lab)]),
          h('strong', {}, I18N.name(l.name)), Tasks.badge(l.task)),
        Tasks.colourBasis(l.metrics) ? h('div', {class: 'muted small'}, Tasks.colourBasis(l.metrics)) : null,
        h('div', {class: 'small muted'}, params(l)),
        h('div', {class: 'stack small'}, Tasks.metrics(l.metrics, {skip: ['lab']}), (l.notes || []).length ? h('span', {}, l.notes.map((n) => I18N.tr(n)).join(' · ')) : null,
          ...Composition.layerNotes(l))));
      const images = (check.layers || []).filter((l) => l.image && l.tonal);
      // each photographed photo engraving judged as a picture, and the copies of a «Подобрать настройки» plate side by side
      // (photo-engraving-quality REQ-003, DEC-001, DEC-003)
      const judged = images.filter((l) => l.photo_quality).map((l) => PhotoQuality.layerBox(l.name, l.photo_quality));
      const quality = pair.variations ? h('div', {class: 'stack'}, PhotoQuality.variationsBox(pair.variations, shown, pair.status === 'Accepted'),
        judged.length ? h('details', {}, h('summary', {class: 'small'}, `Выводы по каждому слою · ${judged.length}`), h('div', {class: 'stack'}, judged)) : null)
        : judged.length ? h('div', {class: 'stack'}, h('h3', {}, 'Фотогравировка: выводы'), ...judged) : null;
      // an accepted photo engraving: what the grey scale predicted before it against what came out (DEC-117), loaded after the rest
      const review = images.length && pair.status === 'Accepted' ? h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Сравниваем с прогнозом…')) : null;
      fill(result,
        ...(check.problems || []).map((m) => h('div', {class: 'alert bad', role: 'alert'}, I18N.tr(m))),
        ...(check.warnings || []).map((m) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(m))),
        frameNote(check),
        ...(check.composition ? [Composition.card(check)] : []),
        ...(ref ? [h('div', {class: 'alert ok', role: 'status'},
          `Цвета приведены к чистому титану этой же фотографии (слой очистки: L* ${num(ref.lab[0], 1)} как снято, принят за L* ${num(ref.nominal[0], 0)}`
          + `${ref.nominal_source === 'chart' ? ', по измерениям с картой' : ', значение по умолчанию'}). `
          + (Math.abs(ref.exposure_stops) >= 1 ? `Снимок ${ref.exposure_stops > 0 ? 'темнее' : 'светлее'} номинала на ${num(Math.abs(ref.exposure_stops), 1)} ступени экспозиции; ` : '')
          + 'отношение цвета к чистому титану в линейном свете от экспозиции не зависит.')] : []),
        review,
        quality,
        layers.length ? h('div', {class: 'stack'}, h('h3', {}, `Измеренные слои · ${layers.length}`),
          h('p', {class: 'muted small'}, ref ? 'Цвет относительно чистого титана, затем слой, задача, параметры, метрики и заметки.' : 'Цвет на фото, затем слой, задача, параметры, метрики и заметки.'),
          h('div', {class: 'ep-layers'}, rows)) : h('p', {class: 'muted'}, 'Измерений пока нет: откройте проверку.'),
        ...images.map((l) => h('p', {class: 'small'}, `${l.name}: тональный профиль — связь серого уровня картинки с яркостью ${num(l.tonal.rho, 2)}, `
          + `размах L* ${num(l.tonal.range_L, 0)}. `, link(`/ingest?pair=${shown}`, 'Таблица «серый → мощность → цвет»'))));
      if (review) PredictionReview.load(shown, review, () => !!current && current.id === shown);
      fill(matrixBox, pair.matrix ? [h('h3', {}, `Матрица параметров ${pair.matrix.cols} × ${pair.matrix.rows}`),
        h('p', {class: 'muted small'}, pair.matrix.confirmed ? 'Настройки прочитаны с фотографии и подтверждены.' : 'Настройки прочитаны с фотографии и ещё не подтверждены.'),
        IngestReview.matrixGrid(pair)] : null);
      showMatrixTab(!!pair.matrix);
    }
    function refreshAll() { showTools(); showPhoto(); showChecks(); showResult().catch(fail); }

    // -- плата, выводы, действия -------------------------------------------------------------------------------------
    // a photo work is not a plate: it is opened, changed and exported on its own screen (0.19.3)
    const photoWork = exp.plate && exp.plate.mode === 'Photo engraving work';
    const plate = photoWork ? h('div', {class: 'stack'}, h('h3', {}, 'Работа фотогравировки'),
      h('p', {}, h('strong', {}, exp.plate.name)), h('p', {class: 'muted small'}, exp.plate.identifier || ''),
      h('div', {class: 'row'}, link('/photo-engraving?work=' + exp.plate.plan_id, 'Открыть работу'),
        h('a', {class: 'btn btn-small', href: `/api/photo-works/${exp.plate.plan_id}/export.lbrn2`}, 'Скачать .lbrn2')))
      : exp.plate ? h('div', {class: 'stack'}, h('h3', {}, 'Плата'),
      h('p', {}, h('strong', {}, I18N.name(exp.plate.name))),
      h('p', {class: 'muted small'}, [exp.plate.test_name || I18N.name(exp.plate.mode), `${exp.plate.layers} слоёв`, exp.plate.band_count ? `${exp.plate.band_count} полос` : null,
        exp.plate.identifier].filter(Boolean).join(' · ')),
      exp.plate.description ? h('p', {class: 'small'}, exp.plate.description) : null,
      App.timeBlock(exp.time),
      // a plate of the experiment designer answers its proposal (REQ-022): the proposal shows this plate's result
      exp.plate.proposal ? h('p', {class: 'small'}, 'Сделана по ', link(`/designer?device=${exp.plate.proposal.device_id}&lens=${App.lensParam(exp.plate.proposal.lens_id)}&proposal=${exp.plate.proposal.id}`,
        `предложению планировщика № ${exp.plate.proposal.id}`)) : null,
      exp.plate.engraving_task ? h('p', {class: 'small'}, h('strong', {}, 'Задача: '), Tasks.name(exp.plate.engraving_task.kind),
        exp.plate.engraving_task.basis === 'explicit' ? '' : ' (по режиму плана)',
        Object.keys(exp.plate.engraving_task.goals || {}).length ? ` · ${Tasks.goalsText(exp.plate.engraving_task.goals)}` : '') : null,
      h('div', {class: 'row'}, link('/plans/' + exp.plate.plan_id, 'Открыть и изменить плату'),
        h('a', {class: 'btn btn-small', href: `/api/plans/${exp.plate.plan_id}/export.lbrn2`}, 'Скачать .lbrn2'),
        link('/research', 'Попросить AI-исследователя изменить плату'))) : null;
    const work = pairs[pairs.length - 1];
    // REQ-030: an accepted grayscale photo engraving opens its own file in the preview at other Min and Max power
    const photoEngraving = pairs.slice().reverse().find((p) => p.status === 'Accepted' && (p.grayscale_image || p.tonal_image));
    const files = !exp.plate && work ? h('div', {class: 'stack'}, h('h3', {}, 'Готовая работа'),
      h('p', {class: 'muted small'}, `Файл LightBurn: ${work.lightburn_name}`), App.timeBlock(exp.time),
      h('div', {class: 'row'}, h('a', {class: 'btn btn-small', href: work.lightburn_url, download: work.lightburn_name}, 'Скачать файл LightBurn'),
        photoEngraving ? link(`/photo-preview?pair=${photoEngraving.id}`, 'Как будет выглядеть при других Min/Max') : null)) : null;
    const findings = exp.findings.length ? h('div', {class: 'stack'}, h('h3', {}, 'Выводы по этому эксперименту'),
      ...exp.findings.map((f) => h('div', {class: 'stack'}, h('p', {}, h('strong', {}, ({line: 'Линии', text: 'Текст', color: 'Цвет', image: 'Изображение'})[f.purpose] || f.purpose),
        ' ', pill(f.status === 'candidate' ? 'Кандидат' : 'Нужен тест', f.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'small'}, f.summary), f.next_test ? h('p', {class: 'muted small'}, f.next_test) : null,
        // a recalculated conclusion keeps what it said before (REQ-022): earlier versions with the time they were in force
        f.history?.length ? h('details', {class: 'small'}, h('summary', {}, `Прежние версии вывода: ${f.history.length}`),
          ...f.history.map((v) => h('p', {class: 'muted'}, `${when(v.valid_from)} — ${when(v.replaced_at)}: `, v.summary))) : null))) : null;
    const acceptedPair = pairs.slice().reverse().find((p) => p.status === 'Accepted');
    const photoLink = (route) => h('a', {class: 'btn btn-small', href: '#' + route}, 'Добавить фото');
    const addPhoto = exp.plan_id ? photoLink('/ingest?plan=' + exp.plan_id)
      : acceptedPair ? photoLink('/ingest?rephoto=' + acceptedPair.id)
        : h('span', {class: 'muted small'}, 'Фото можно добавить после принятия проверки');
    const remove = btn('Удалить эксперимент', () => confirmBox('Удалить эксперимент',
      `«${I18N.name(exp.title)}»: будут удалены ${exp.plan_id ? 'плата и ' : ''}все проверки (${pairs.length}) с загруженными копиями файлов. История измерений сохранится, но перестанет влиять на рекомендации.`,
      'Удалить', async () => {
        for (const p of pairs) await del('/pairs/' + p.id);       // each check on its own, then the plate (DEC-047)
        if (exp.plan_id) await del(`/plans/${exp.plan_id}`);
        toast('Эксперимент удалён', 'ok'); go('/experiments');
      }), 'btn-small danger');

    // -- tabs on the right: only the sections this experiment has -------------------------------------------------------------
    const items = [
      ...(pairs.length ? [['result', 'Результат', result], ['matrix', 'Матрица', matrixBox], ['checks', `Проверки (${pairs.length})`, checks]] : []),
      ...(plate ? [['plate', photoWork ? 'Работа фотогравировки' : 'Плата', plate]] : []), ...(files ? [['work', 'Работа', files]] : []),
      ...(findings ? [['findings', `Выводы (${exp.findings.length})`, findings]] : [])];
    const box = App.tabs(items, {initial: items[0][0], remember: 'ep.tab', label: 'Разделы эксперимента', prefix: 'ep-tab'});
    // the matrix tab is there only while the shown check has a parameter matrix
    const matrixTab = [...box.list.querySelectorAll('button')].find((b) => b.getAttribute('id') === 'ep-tab-matrix');
    if (matrixTab) matrixTab.hidden = true;
    function showMatrixTab(on) {
      if (!matrixTab) return;
      matrixTab.hidden = !on;
      if (!on && matrixTab.classList.contains('active')) box.select('result');
    }
    refreshAll();
    const sub = [I18N.name(exp.kind), exp.laser, exp.lens, exp.material].filter(Boolean).join(' · ') + (exp.created_at ? ` · ${when(exp.created_at)}` : '');
    const name = h('h2', {}, I18N.name(exp.title));
    const titleBox = h('div', {class: 'ep-title', title: `${I18N.name(exp.title)} · ${sub}`});
    // only the name changes; the list of experiments shows the new one when it is opened again
    const pencil = VectorWorkspace.renameButton(exp.key, exp.title, (stored) => {
      exp.title = stored; fill(name, I18N.name(stored)); titleBox.setAttribute('title', `${I18N.name(stored)} · ${sub}`);
    }, '/experiments', 'experiment');
    const head = h('header', {class: 'os-head ep-head'}, h('a', {class: 'btn btn-small', href: '#/experiments'}, '← Эксперименты'),
      fill(titleBox, h('div', {class: 'ep-name'}, name, pencil),
        h('div', {class: 'ep-sub'}, h('span', {class: 'sub'}, sub),
          (exp.tasks || []).length ? [h('span', {class: 'muted small'}, 'Задачи:'), ...exp.tasks.map((k) => pill(Tasks.name(k)))] : null)),
      h('span', {class: 'spacer'}), pill(exp.status_text, STATUS_KIND[exp.status] || ''), addPhoto, remove);
    return h('div', {class: 'os experiment'}, head,
      h('div', {class: 'os-body ep-body'},
        h('section', {class: 'os-col ep-photo-col', 'aria-label': 'Фото с наложением'}, photoTools, stage, caption),
        h('aside', {class: 'os-col ep-side', 'aria-label': 'Сведения об эксперименте'}, box.list, h('div', {class: 'os-scroll ep-panels'}, box.panels))));
  }});
})();
