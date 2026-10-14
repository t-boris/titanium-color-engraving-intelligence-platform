/* Проверка пары: эталон, выравнивание, расхождения с платой, маски слоёв, принятие (REQ-001, REQ-009, REQ-015, DEC-017).
   Принять можно только после проверки без проблем, подтверждения файла при расхождении и проверки масок. */
'use strict';
const IngestReview = (() => {
  const {h, btn, link, pill, post, del, toast, fail, go, confirmBox, num} = App;

  function masks(pair, reload) {
    const ready = pair.status === 'Ready to accept';
    const flag = h('input', {type: 'checkbox', checked: pair.masks_reviewed, disabled: !ready || pair.masks_reviewed});
    const accept = btn('Принять наблюдения', async (ev) => {
      ev.currentTarget.disabled = true;
      try { await post(`/pairs/${pair.id}/accept`); toast('Наблюдения приняты', 'ok'); go('/analysis/' + pair.id); }
      catch (e) { fail(e); ev.currentTarget.disabled = false; }
    }, 'primary', !ready || !pair.masks_reviewed);
    flag.addEventListener('change', async () => {
      if (!flag.checked) return;
      try { await post(`/pairs/${pair.id}/review-masks`); reload(); } catch (e) { flag.checked = false; fail(e); }
    });
    const src = (corrected) => `/api/pairs/${pair.id}/overlay.png?corrected=${corrected}&t=${Date.now()}`;
    const img = h('img', {src: src(true), alt: 'Фотография после коррекции с контурами масок слоёв', style: 'max-width:100%;border-radius:10px'});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Маски слоёв на фотографии'), img,
      h('div', {class: 'row'}, btn('Показать до коррекции', () => { img.src = src(false); }), btn('Показать после коррекции', () => { img.src = src(true); })),
      h('label', {class: 'row'}, flag, h('span', {}, 'Маски слоёв проверены: контуры лежат на нужных областях, края исключены')),
      ready ? null : h('p', {class: 'muted small'}, 'Принять можно после проверки без проблем и подтверждения файла при расхождении.'),
      h('div', {class: 'row'}, accept));
  }

  function cornersCard(pair, run) {
    let corners = null;
    const apply = btn('Применить выравнивание', () => run({corners_fraction: corners}), 'primary', true);
    const picker = Corners.create(`/api/pairs/${pair.id}/photo.png`, null, (c) => { corners = c; apply.disabled = !c; });
    return {card: h('div', {class: 'card stack'}, h('h3', {}, 'Углы работы на фотографии'), picker.el, h('div', {class: 'row'}, apply)), get: () => corners};
  }

  async function render(pair, reload) {
    if (pair.status === 'Accepted') {
      return h('div', {class: 'stack'}, h('div', {class: 'alert ok'}, 'Пара файлов и измеренный цвет неизменяемы.'),
        h('div', {class: 'row'}, link('/analysis/' + pair.id, 'Открыть анализ'), link('/ingest?rephoto=' + pair.id, 'Повторная фотография этого изделия')));
    }
    const check = pair.check;
    const run = async (body) => {
      try { await post(`/pairs/${pair.id}/check`, body || {}); toast('Проверка выполнена', 'ok'); reload(); } catch (e) { fail(e); }
    };
    const out = h('div', {class: 'stack'});
    out.append(h('div', {class: 'card'}, h('h3', {}, 'Пара'), h('p', {}, `${pair.lightburn_name} + ${pair.photo_name}`),
      h('div', {class: 'row'}, btn(check ? 'Повторить проверку' : 'Проверить пару', () => run({}), 'primary'),
        btn('Удалить пару', () => confirmBox('Удалить пару', 'Действие необратимо.', 'Удалить', async () => { await del('/pairs/' + pair.id); toast('Запись удалена', 'ok'); go('/experiments'); }), 'danger'))));
    if (!check) {
      out.append(h('p', {class: 'muted'}, 'Нажмите «Проверить пару»: будут прочитаны слои, найден эталон и выровнена фотография.'));
      return out;
    }
    out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Результаты проверки'),
      h('p', {}, 'Эталонная карта: ', check.chart.detected ? pill('обнаружена', 'ok') : pill('не обнаружена', 'bad'),
        check.chart.residual != null ? ` · остаточная ошибка коррекции ΔE ${num(check.chart.residual, 1)}` : ''),
      h('p', {}, 'Выравнивание: ', check.alignment.valid ? pill(check.alignment.method === 'markers' ? 'по маркерам' : 'вручную по углам', 'ok') : pill('не выполнено', 'warn')),
      ...check.problems.map((m) => h('div', {class: 'alert bad', role: 'alert'}, I18N.tr(m)))));
    if (!check.alignment.valid && check.problems.some((m) => /four image corners/i.test(m))) out.append(cornersCard(pair, run).card);
    if (check.discrepancies.length) {
      const conf = pair.file_confirmation;
      out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Сравнение с определением платы'),
        h('div', {class: 'alert warn'}, 'Параметры файла отличаются от определения платы. Исправьте пару или подтвердите использованный файл.'),
        IngestDialogs.discrepancyTable(check.discrepancies),
        conf ? h('p', {class: 'alert ok'}, `Подтверждено: «${conf.text}» · ${conf.at.slice(0, 16).replace('T', ' ')}`)
          : h('div', {class: 'row'}, btn('Исправить пару', () => IngestDialogs.fixFile(pair, reload)),
            btn('Подтвердить использованный файл', () => IngestDialogs.confirmFile(pair, check, reload)))));
    }
    out.append(h('div', {class: 'card stack'}, h('h3', {}, 'Слои файла'), IngestDialogs.layersTable(check.layers)));
    if (check.alignment.valid) out.append(masks(pair, reload));
    return out;
  }
  return {render};
})();
