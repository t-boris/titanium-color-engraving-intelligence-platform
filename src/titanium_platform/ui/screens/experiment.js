/* Эксперимент как один объект (REQ-028, DEC-055): фото с наложением всегда на виду, под ним результат, плата, выводы и все проверки.
   Маршрут /experiment/:ключ, где ключ plan-<id> (плата и её проверки) или eng-<id> (готовая работа и её фото). */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, del, toast, confirmBox, go, fail, num, swatch, labText, table} = App;
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
    p.pulse_width != null ? `${num(p.pulse_width, 0)} нс` : supplied(p, 'pulse_width') ? `${num(supplied(p, 'pulse_width').value, 0)} нс (введено оператором)` : 'Q-Pulse нет в файле',
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
    let lifted = sessionStorage.getItem('experiment-lifted') !== '0';
    let contours = sessionStorage.getItem('experiment-contours') !== '0';

    // -- фото с наложением: первый блок страницы, показывается всегда ----------------------------------------------
    const stage = h('div', {class: 'exp-stage'});
    const caption = h('p', {class: 'muted small'});
    const photoTools = h('div', {class: 'row exp-tools'});
    const checks = h('div', {class: 'exp-checks'});
    const result = h('div', {class: 'stack'});
    // the photograph is shown the way its colours were measured: corrected by the chart when a chart was used,
    // so that the swatches and the picture share one exposure (the RAW as shot is darker)
    const shownCorrected = (pair) => pair.measurement === 'reference_chart_corrected';
    function url(pair) {
      const base = '/api/pairs/' + pair.id, stamp = pair.accepted_at || pair.created_at || '';
      const view = `corrected=${shownCorrected(pair)}&visibility=${lifted ? 'lifted' : 'normal'}&full=false&t=${encodeURIComponent(stamp)}`;
      return contours && pair.alignment ? `${base}/overlay.png?${view}` : `${base}/photo.png?${view}`;
    }
    function showPhoto() {
      if (!current) {
        stage.replaceChildren(h('div', {class: 'card empty exp-nophoto'}, h('h3', {}, 'Фото ещё нет'),
          h('p', {class: 'muted'}, 'Плата готова. Выгравируйте её и добавьте фото: оно появится здесь с наложением контуров.'),
          exp.plan_id ? link('/ingest?plan=' + exp.plan_id, 'Добавить фото') : null));
        caption.textContent = '';
        return;
      }
      const img = h('img', {class: 'exp-photo', alt: `Фото «${current.photo_name}» с наложением контуров`, src: url(current)});
      img.addEventListener('error', () => {       // проверка ещё не выровняла фото: покажем снимок без контуров
        if (!img.dataset.plain) { img.dataset.plain = '1'; img.src = `/api/pairs/${current.id}/photo.png?corrected=${shownCorrected(current)}&visibility=${lifted ? 'lifted' : 'normal'}&full=false`; }
      });
      stage.replaceChildren(h('a', {href: `/api/pairs/${current.id}/overlay.png?corrected=${shownCorrected(current)}&full=true&visibility=${lifted ? 'lifted' : 'normal'}`,
        target: '_blank', rel: 'noopener', title: 'Открыть в полном размере'}, img));
      const method = current.alignment ? `Выравнивание ${ALIGN[current.alignment] || current.alignment}` : 'Фото ещё не выровнено';
      caption.textContent = `${current.photo_name} · проверка №${current.id} · ${method}`
        + (current.measurement ? ` · цвет ${MEASURE[current.measurement] || current.measurement}` : '')
        + (shownCorrected(current) ? ' · фото показано после коррекции по карте, в той же экспозиции, что и плашки' : ' · фото показано как снято');
    }
    function showTools() {
      photoTools.replaceChildren(
        btn(contours ? 'Скрыть контуры' : 'Показать контуры', () => { contours = !contours; sessionStorage.setItem('experiment-contours', contours ? '1' : '0'); refreshAll(); }, 'btn-small'),
        btn(lifted ? 'Обычная яркость' : 'Поднять яркость', () => { lifted = !lifted; sessionStorage.setItem('experiment-lifted', lifted ? '1' : '0'); refreshAll(); }, 'btn-small'),
        h('span', {class: 'muted small'}, 'Зелёные линии — контуры картинки, найденные на фото; цветные — векторы LightBurn; розовые — продолжение под рамкой.'));
    }
    function showChecks() {
      checks.replaceChildren(...pairs.slice().reverse().map((p) => {
        const [label, kind] = KIND[p.status] || [p.status, ''];
        return h('div', {class: 'exp-check' + (current && p.id === current.id ? ' is-current' : '')},
          btn(`Проверка №${p.id}`, () => { current = p; refreshAll(); }, 'btn-small'),
          h('span', {class: 'exp-check-name', title: p.photo_name}, p.photo_name), pill(label, kind),
          h('span', {class: 'muted small'}, when(p.accepted_at || p.created_at)),
          h('span', {class: 'spacer'}),
          link(p.status === 'Accepted' ? `/analysis/${p.id}` : `/ingest?pair=${p.id}`, p.status === 'Accepted' ? 'Разбор' : 'Проверить и принять'),
          btn('Удалить', () => confirmBox('Удалить проверку', `Проверка №${p.id} и её измерения исчезнут из активной базы.`, 'Удалить',
            async () => { await del('/pairs/' + p.id); toast('Проверка удалена', 'ok'); reload(); }), 'btn-small danger'));
      }));
    }
    async function showResult() {
      if (!current) { result.replaceChildren(); return; }
      const shown = current.id;
      const pair = await get('/pairs/' + shown);
      if (!current || current.id !== shown) return;
      const check = pair.check || {};
      const layers = (check.layers || []).filter((l) => l.measured_lab);
      const ref = check.clean_reference;
      // REQ-020: у каждого слоя — его задача; у каждой метрики — способ (подсказка) и основание измерения
      const rows = layers.map((l) => [
        h('span', {}, l.measured_lab_against_clean
          ? [swatch(l.measured_lab_against_clean), labText(l.measured_lab_against_clean), h('span', {class: 'muted small'}, ` · как снято: ${labText(l.measured_lab)}`)]
          : [swatch(l.measured_lab), labText(l.measured_lab)],
        Tasks.colourBasis(l.metrics) ? h('div', {class: 'muted small'}, Tasks.colourBasis(l.metrics)) : null),
        I18N.name(l.name), Tasks.badge(l.task), params(l),
        h('div', {class: 'stack small'}, Tasks.metrics(l.metrics, {skip: ['lab']}), (l.notes || []).length ? h('span', {}, l.notes.map((n) => I18N.tr(n)).join(' · ')) : null)]);
      const images = (check.layers || []).filter((l) => l.image && l.tonal);
      fill(result,
        ...(check.problems || []).map((m) => h('div', {class: 'alert bad', role: 'alert'}, I18N.tr(m))),
        ...(check.warnings || []).map((m) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(m))),
        frameNote(check),
        ...(ref ? [h('div', {class: 'alert ok', role: 'status'},
          `Цвета приведены к чистому титану этой же фотографии (слой очистки: L* ${num(ref.lab[0], 1)} как снято, принят за L* ${num(ref.nominal[0], 0)}`
          + `${ref.nominal_source === 'chart' ? ', по измерениям с картой' : ', значение по умолчанию'}). `
          + (Math.abs(ref.exposure_stops) >= 1 ? `Снимок ${ref.exposure_stops > 0 ? 'темнее' : 'светлее'} номинала на ${num(Math.abs(ref.exposure_stops), 1)} ступени экспозиции; ` : '')
          + 'отношение цвета к чистому титану в линейном свете от экспозиции не зависит.')] : []),
        pair.matrix ? h('div', {class: 'card stack'}, h('h3', {}, `Матрица параметров ${pair.matrix.cols} × ${pair.matrix.rows}`),
          h('p', {class: 'muted small'}, pair.matrix.confirmed ? 'Настройки прочитаны с фотографии и подтверждены.' : 'Настройки прочитаны с фотографии и ещё не подтверждены.'),
          IngestReview.matrixGrid(pair)) : null,
        layers.length ? h('div', {class: 'card stack'}, h('h3', {}, `Измеренные слои · ${layers.length}`),
          table([ref ? 'Цвет относительно чистого титана' : 'Цвет на фото', 'Слой', 'Задача', 'Параметры', 'Метрики и заметки'], rows)) : h('p', {class: 'muted'}, 'Измерений пока нет: откройте проверку.'),
        ...images.map((l) => h('p', {class: 'small'}, `${l.name}: тональный профиль — связь серого уровня картинки с яркостью ${num(l.tonal.rho, 2)}, `
          + `размах L* ${num(l.tonal.range_L, 0)}. `, link(`/ingest?pair=${shown}`, 'Таблица «серый → мощность → цвет»'))));
    }
    function refreshAll() { showTools(); showPhoto(); showChecks(); showResult().catch(fail); }

    // -- плата, выводы, действия -------------------------------------------------------------------------------------
    const plate = exp.plate ? h('div', {class: 'card stack'}, h('h3', {}, 'Плата'),
      h('p', {}, h('strong', {}, exp.plate.name)),
      h('p', {class: 'muted small'}, [exp.plate.test_name || exp.plate.mode, `${exp.plate.layers} слоёв`, exp.plate.band_count ? `${exp.plate.band_count} полос` : null,
        exp.plate.identifier].filter(Boolean).join(' · ')),
      exp.plate.description ? h('p', {class: 'small'}, exp.plate.description) : null,
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
    const photoEngraving = pairs.slice().reverse().find((p) => p.status === 'Accepted' && p.grayscale_image);
    const files = !exp.plate && work ? h('div', {class: 'card stack'}, h('h3', {}, 'Готовая работа'),
      h('p', {class: 'muted small'}, `Файл LightBurn: ${work.lightburn_name}`),
      h('div', {class: 'row'}, h('a', {class: 'btn btn-small', href: work.lightburn_url, download: work.lightburn_name}, 'Скачать файл LightBurn'),
        photoEngraving ? link(`/photo-preview?pair=${photoEngraving.id}`, 'Как будет выглядеть при других Min/Max') : null)) : null;
    const findings = exp.findings.length ? h('div', {class: 'card stack'}, h('h3', {}, 'Выводы по этому эксперименту'),
      ...exp.findings.map((f) => h('div', {class: 'stack'}, h('p', {}, h('strong', {}, ({line: 'Линии', text: 'Текст', color: 'Цвет', image: 'Изображение'})[f.purpose] || f.purpose),
        ' ', pill(f.status === 'candidate' ? 'Кандидат' : 'Нужен тест', f.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'small'}, f.summary), f.next_test ? h('p', {class: 'muted small'}, f.next_test) : null,
        // a recalculated conclusion keeps what it said before (REQ-022): earlier versions with the time they were in force
        f.history?.length ? h('details', {class: 'small'}, h('summary', {}, `Прежние версии вывода: ${f.history.length}`),
          ...f.history.map((v) => h('p', {class: 'muted'}, `${when(v.valid_from)} — ${when(v.replaced_at)}: `, v.summary))) : null))) : null;
    const acceptedPair = pairs.slice().reverse().find((p) => p.status === 'Accepted');
    const addPhoto = exp.plan_id ? link('/ingest?plan=' + exp.plan_id, 'Добавить фото')
      : acceptedPair ? link('/ingest?rephoto=' + acceptedPair.id, 'Добавить фото')
        : h('span', {class: 'muted small'}, 'Фото можно добавить после принятия проверки');
    const remove = btn('Удалить эксперимент', () => confirmBox('Удалить эксперимент',
      `«${I18N.name(exp.title)}»: будут удалены ${exp.plan_id ? 'плата и ' : ''}все проверки (${pairs.length}) с загруженными копиями файлов. История измерений сохранится, но перестанет влиять на рекомендации.`,
      'Удалить', async () => {
        for (const p of pairs) await del('/pairs/' + p.id);       // each check on its own, then the plate (DEC-047)
        if (exp.plan_id) await del(`/plans/${exp.plan_id}`);
        toast('Эксперимент удалён', 'ok'); go('/experiments');
      }), 'btn-small danger');

    refreshAll();
    return h('div', {class: 'stack experiment'},
      h('div', {class: 'row exp-head'}, h('div', {}, link('/experiments', '← Эксперименты'),
        h('h2', {}, I18N.name(exp.title)),
        h('p', {class: 'sub'}, [exp.kind, exp.laser, exp.lens, exp.material].filter(Boolean).join(' · ')
          + (exp.created_at ? ` · ${when(exp.created_at)}` : '')),
        (exp.tasks || []).length ? h('div', {class: 'row small'}, h('span', {class: 'muted'}, 'Задачи:'), ...exp.tasks.map((k) => pill(Tasks.name(k)))) : null),
        h('span', {class: 'spacer'}), pill(exp.status_text, STATUS_KIND[exp.status] || ''), addPhoto, remove),
      h('section', {class: 'card stack exp-photo-card'}, photoTools, stage, caption),
      checks,
      result,
      plate, files, findings);
  }});
})();
