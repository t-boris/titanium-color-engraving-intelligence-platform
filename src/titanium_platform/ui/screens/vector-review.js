/* Результат гравировки и «работа над ошибками» (DEC-090, предложено): вкладка «Результат» работы из фотографии.
   Верх: что ожидали от файла LightBurn и что вышло. Гравировку выбирает оператор (список с номером файла и датой), основание сравнения названо
   прямо: прогноз, сохранённый вместе с файлом, или реконструкция по слоям работы, или его нет (feature ux-engraving-lifecycle-p0, REQ-003).
   Оценка цвета и оценка фотослоя идут отдельными разделами и друг друга не заменяют. Для каждой гравировки работы, по которой принято фото,
   слои файла сопоставлены со слоями фотографии по настройкам (не по номеру: гравировали не обязательно тот файл, который сделала работа): цвет «ожидали → получилось»,
   разница ΔE и по светлоте, что видно по самим измерениям (блик, другая основа измерения, фото без карты) и общий сдвиг, если почти все
   слои ушли в одну сторону. Две картинки одной работы рядом: в обещанных цветах и в полученных.
   Низ: текущий прогноз работы относительно её последнего файла; он не исправляет выгравированный файл. После новых измерений цвет рецепта мог измениться; слои, где он ушёл заметно,
   перечислены с самой близкой к исходному цвету заменой и кнопкой «Заменить». Замена — обычная правка работы; сразу после неё сказано,
   что заменено, и есть «Отменить замену». Выгравированный файл замена не трогает. Вкладка узкая, поэтому слои идут строками, а подробности открываются по нажатию. */
'use strict';
const VectorReview = (() => {
  const {h, fill, btn, num, link, modal} = App;
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const rgb = (c, title) => h('span', {class: 'sw', style: `background:rgb(${c.join(',')})`, title});
  const signed = (v, d = 1) => (v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d));
  const percent = (share) => `${Math.round((share || 0) * 100)} %`;
  const sq = (mm2) => `${num(mm2 / 100, 1)} см²`;
  const BASIS = {chart: 'по эталонной карте', clean: 'относительно чистого титана', 'as-shot': 'как снято'};
  const CAUSE = {
    highlight: (c) => `слой светлее белого квадрата карты (L* ${num(c.L, 1)}): блик, цвет обрезан и настоящий не измерен`,
    basis: (c) => `цвет обещан ${BASIS[c.promised] || c.promised}, а получен ${BASIS[c.got] || c.got}: сравнение приблизительное`,
    relative_photo: () => 'фото без эталонной карты: цвет относительный, не абсолютный'};
  const NOTE = {
    poor_chart: (n) => `Карта на этом фото прочитана неточно (ошибка ${num(n.residual, 1)} ΔE), поэтому меньшие различия ошибками не считаются.`,
    systematic: (n) => `Почти все слои сместились в одну сторону (медиана ΔL ${signed(n.dL)}): похоже на экспозицию фото или партию титана, а не на рецепты.`};
  const LOST = 'Файл создан до того, как работа стала запоминать ожидаемые цвета, а после него работу перекрасили или разбили заново: что он обещал, '
    + 'уже не восстановить, поэтому сравнения нет. Измеренные слои фото перечислены ниже; следующий файл из работы запомнит свои цвета.';
  const TOP = 5;                                 // the largest differences named first; the rest on request
  const shown = new Map();                       // какую гравировку работы показывать: удобство одного зрителя, не состояние работы

  // ---- результат гравировки -----------------------------------------------------------------------------------------------------

  const PHOTO_SETTINGS = {power: 'максимальная мощность, %', min_power: 'минимальная мощность, %', pulse_width: 'импульс, нс',
    line_interval: 'шаг, мм', speed: 'скорость, мм/с', frequency: 'частота, кГц', dither: 'вид'};

  function photoResult(p) {
    const t = p.tone;
    return h('div', {class: 'stack'}, h('h4', {}, p.zone ? `Фотозона ${p.zone}` : p.name),
      (p.changed_settings || []).length ? h('div', {class: 'alert warn'},
        `Выгравированные настройки отличаются от файла № ${p.latest_export}: `,
        p.changed_settings.map((k) => `${PHOTO_SETTINGS[k] || k}: ${p.settings[k]} → ${p.latest_settings[k]}`).join('; '),
        '. Сравнение относится к выгравированным настройкам.') : null,
      p.median_de == null ? h('p', {class: 'small muted'}, 'Для настроек этого фотослоя до гравировки не было измеренной шкалы: точность прогноза не оценена.')
        : h('p', {}, `Прогноз фотослоя по прежним измерениям: медиана ошибки ${num(p.median_de, 1)} ΔE, максимум ${num(p.max_de, 1)} ΔE.`),
      t ? h('p', {class: 'small'}, `На фото: различимых тонов ${t.levels} из ${t.steps}; светлота от ${num(t.black_L, 1)} до ${num(t.white_L, 1)} L*.`) : null,
      h('p', {class: 'small muted'}, p.profile_usable
        ? 'Измеренные тона участвуют в следующих прогнозах этого фотослоя на тех же настройках.'
        : 'Измеренные тона не участвуют в прогнозе: соответствие картинки и фотографии пока не подтверждено.'));
  }

  function detail(row) {
    const causes = row.causes.map((c) => h('li', {}, (CAUSE[c.code] || (() => c.code))(c)));
    modal(row.name, h('div', {class: 'stack'},
      h('p', {}, rgb(row.promised_srgb, 'ожидали'), `Ожидали: ${App.labText(row.promised_lab)}`),
      h('p', {}, rgb(row.got_srgb, 'получилось'), `Получилось: ${App.labText(row.got_lab)}`),
      h('p', {}, `ΔE ${num(row.delta_e, 1)} · светлота ${signed(row.dL)} · насыщенность ${signed(row.dC)}` + (row.dh == null ? '' : ` · оттенок ${signed(row.dh, 0)}°`)),
      h('p', {class: 'small muted'}, `Слой в ожидании: ${row.promised_name}; площадь ${sq(row.area_mm2)}.`),
      causes.length ? h('div', {}, h('strong', {}, 'Что видно по измерениям'), h('ul', {}, causes))
        : h('p', {class: 'small muted'}, 'По самим измерениям причины не найдено: слой измерен как положено, цвет вышел другим. Возможно, другой титан или фокус.')),
      [{label: 'Закрыть', cls: 'primary', run: (m) => m.close()}]);
  }

  function rowLine(row) {
    return h('button', {type: 'button', class: 'vw-line vw-review-row', onClick: () => detail(row)},
      h('span', {}, rgb(row.promised_srgb, 'ожидали'), '→', rgb(row.got_srgb, 'получилось'), row.name),
      h('span', {class: 'small ' + (row.beyond ? 'vw-bad' : 'muted')}, `ΔE ${num(row.delta_e, 1)} · ΔL ${signed(row.dL)}`));
  }

  // a photograph opened from here is linked to this work: the form takes its laser, lens and titanium from it
  const uploadLink = (j) => link(`/ingest?plan=${j.id}` + (j.material_id ? `&material=${j.material_id}` : ''), 'Загрузить фото для этой работы');

  /** Оценка цвета одной гравировки: итог, картинки «ожидали / получилось» в одном масштабе, крупнейшие отличия, чего не нашли. Оценка
      фотослоя сюда не входит: у неё свой раздел, и один другой не заменяет. */
  function colourSection(j, r) {
    const t = r.summary;
    const rows = [...r.rows].sort((a, b) => b.delta_e - a.delta_e);
    const pic = (promised) => h('figure', {class: 'vw-review-pic'}, h('img', {alt: promised ? 'Работа в ожидаемых цветах' : 'Работа в полученных цветах', loading: 'lazy',
      src: `/api/vector/${j.id}/engraved.png?engraving=${encodeURIComponent(r.engraving_id)}&promised=${promised}&v=${encodeURIComponent(r.reviewed_at)}`}),
      h('figcaption', {class: 'small'}, promised ? 'Ожидали' : 'Получилось'));
    const worst = h('div', {class: 'vw-lines'});
    let all = false;
    const drawWorst = () => {
      fill(worst, (all ? rows : rows.slice(0, TOP)).map(rowLine), rows.length > TOP ? btn(all ? 'Показать только крупнейшие' : `Показать все (${rows.length})`,
        () => { all = !all; drawWorst(); }, 'btn-small') : null);
    };
    drawWorst();
    return h('section', {class: 'stack', 'aria-label': 'Оценка цвета'}, h('h5', {}, 'Оценка цвета'),
      r.promise_lost ? h('div', {class: 'alert warn'}, LOST)
      : t.matched === 0 ? h('div', {class: 'alert warn'}, 'Ни один слой гравированного файла не совпал по настройкам со слоями файла этой работы. Это другой файл (его правили в LightBurn '
        + 'или сделали не из этой работы): сравнивать нечего.')
        : h('p', {}, `Совпало слоёв ${t.matched} из ${t.promised} ожидаемых. Средняя разница ${num(t.mean_delta_e, 1)} ΔE по площади; заметно отличаются ${t.beyond_layers} слоёв `
          + `(${percent(t.area_share_beyond)} площади). Порог ${num(r.limit, 1)} ΔE.`),
      ...r.notes.map((n) => h('div', {class: 'alert'}, (NOTE[n.code] || (() => n.code))(n))),
      t.matched ? h('div', {class: 'vw-review-pics'}, pic(true), pic(false)) : null,
      rows.length ? h('div', {class: 'stack'}, h('h6', {}, 'Крупнейшие отличия'), worst) : null,
      r.not_engraved.length ? h('details', {class: 'vw-details'}, h('summary', {}, `Ожидались, но на фото не найдены (${r.not_engraved.length})`),
        h('div', {class: 'vw-lines'}, r.not_engraved.map((n) => h('div', {class: 'vw-line'}, h('span', {}, n.name), h('span', {class: 'small muted'}, sq(n.area_mm2)))))) : null,
      r.unmatched.length ? h('details', {class: 'vw-details'}, h('summary', {}, `Есть на фото, но не в файле работы (${r.unmatched.length})`),
        h('div', {class: 'vw-lines'}, r.unmatched.map((n) => h('div', {class: 'vw-line'}, h('span', {}, n.name))))) : null);
  }

  /** Оценка фотослоёв одной гравировки (изображение в градациях серого): отдельный раздел со своими числами; None, когда фотослоёв нет. */
  function photoSection(r) {
    return (r.photo || []).length ? h('section', {class: 'stack', 'aria-label': 'Оценка фотослоя'}, h('h5', {}, 'Оценка фотослоя'), ...r.photo.map(photoResult)) : null;
  }

  function resultBlock(j) {
    const head = h('h4', {}, 'Результат гравировки');
    const reviews = j.reviews || [];
    if (!reviews.length) {
      return h('div', {class: 'stack'}, head, h('p', {class: 'small muted'},
        'Фото результата по этой работе ещё не принято. Выгравируйте файл работы без правок слоёв в LightBurn, снимите результат и загрузите фото по ссылке ниже: '
        + 'здесь появится сравнение «ожидали → получилось», а вывод запишется в саму работу.'), h('p', {}, uploadLink(j)));
    }
    const current = reviews.find((r) => r.engraving_id === shown.get(j.id)) || reviews[0];
    const body = h('div', {class: 'stack'});
    const label = (r) => `${r.photo_name} · ${r.export_number ? `файл № ${r.export_number}` : 'работа не выгружалась'} · ${when(r.reviewed_at)}`;
    const picker = h('select', {'aria-label': 'Гравировка', onChange: (ev) => { shown.set(j.id, ev.target.value); fill(body, content(ev.target.value)); }},
      reviews.map((r) => h('option', {value: r.engraving_id, selected: r.engraving_id === current.engraving_id}, label(r))));
    function content(id) {
      const r = reviews.find((x) => x.engraving_id === id) || current;
      return [h('p', {class: 'small'}, `Фото ${r.photo_name} · ${when(r.reviewed_at)} · ` + (r.export_number ? `файл № ${r.export_number}` : 'работа ещё не выгружалась')),
        h('p', {class: 'small' + (r.basis.kind === 'saved' ? ' muted' : ''), role: r.basis.kind === 'saved' ? null : 'note'}, Lifecycle.basisNote(r.basis)),
        colourSection(j, r), photoSection(r)];
    }
    fill(body, content(current.engraving_id));
    return h('div', {class: 'stack'}, head, App.field('Гравировка', picker), body, h('p', {class: 'small'}, uploadLink(j)));
  }

  // ---- цвета работы после новых измерений ---------------------------------------------------------------------------------------

  /** Что заменили последним и можно ли это отменить: удобство зрителя, не состояние работы. ``ops`` — замены (правки раскраски), ``depth`` —
      глубина отмены работы сразу после них (пока null, замены ещё идут). Запись верна, пока в работе нет других правок после замен и сами
      замены на месте: любая следующая правка меняет глубину отмены, правка того же цвета меняет его запись. */
  const replaced = new Map();
  const seen = new Map();                        // глубина отмены работы, какой её нарисовали в последний раз (ответ сервера рисуется до возврата ``run``)
  const intact = (j, done) => (done.depth == null || done.depth === j.undo)
    && done.ops.every((o) => ((j.colours || []).find((c) => c.index === o.op.colour) || {}).entry_id === o.op.entry_id);

  /** Одна замена выполняется как обычная правка раскраски, без побочных действий. */
  async function replace(j, run, ops) {
    const done = {ops: [], depth: null};
    replaced.set(j.id, done);
    for (const one of ops) {
      done.ops.push(one);                          // сначала в запись: экран рисуется ответом сервера ещё до возврата ``run``
      if (!(await run(one.op))) { done.ops.pop(); break; }
      done.depth = seen.get(j.id);
    }
    if (!done.ops.length && replaced.get(j.id) === done) replaced.delete(j.id);
  }

  function replacement(j, p, run) {
    const apply = btn('Заменить', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await replace(j, run, [{op: {op: 'set_colour', colour: p.colour, entry_id: p.entry_id}, de: p.delta_e_proposed}]);
      self.disabled = false;
    }, 'btn-small');
    return h('div', {class: 'vw-line'},
      h('span', {class: 'small'}, rgb(p.srgb, 'исходный цвет'), p.delta_e_now == null ? 'цвет без измерения' : `до исходного ΔE ${num(p.delta_e_now, 1)}`,
        ' → ', rgb(p.entry_srgb, 'предлагается'), `${num(p.delta_e_proposed, 1)}`), apply);
  }

  /** После замены: что сделано и «Отменить замену» (столько шагов назад, сколько замен; Ctrl+Z в редакторе возвращает так же). Пока в работе
      сделана другая правка или замена уже не на месте, сообщения нет: отмена вернула бы не её. */
  function undoNote(j, run) {
    const done = replaced.get(j.id);
    if (!done) return null;
    if (!intact(j, done)) { replaced.delete(j.id); return null; }
    const n = done.ops.length;
    return h('div', {class: 'alert ok row', role: 'status'}, h('span', {}, n > 1 ? `Заменено цветов: ${n}.` : `Исходный цвет заменён на ближайший измеренный (ΔE ${num(done.ops[0].de, 1)}).`,
      ' Выгравированный файл не менялся.'),
      btn('Отменить замену', async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        replaced.delete(j.id);
        for (let i = 0; i < n; i++) { if (!(await run({op: 'undo'}))) break; }
        self.disabled = false;
      }, 'btn-small'));
  }

  function driftBlock(j, run) {
    const a = j.attention || null;
    const head = h('h4', {}, 'Текущий прогноз работы: цвета после новых измерений');
    const note = h('p', {class: 'small muted'}, 'Новые измерения меняют только текущий прогноз работы. Они не исправляют выгравированный файл и не переписывают то, что обещал уже выгруженный файл.');
    if (!a) return h('div', {class: 'stack'}, head, note, undoNote(j, run), h('p', {class: 'small muted'}, 'Файл из этой работы ещё не создавали, поэтому ничего не обещано: предпросмотр уже показывает последние измерения.'));
    if (!a.layers.length) return h('div', {class: 'stack'}, head, note, undoNote(j, run), h('p', {class: 'small muted'},
      'Цвета слоёв совпадают с тем, что обещал последний файл: после него рецепты этой работы заметно не менялись.'));
    const all = a.layers.flatMap((l) => l.proposals.filter((p) => p.entry_id).map((p) => ({op: {op: 'set_colour', colour: p.colour, entry_id: p.entry_id}, de: p.delta_e_proposed})));
    const every = all.length > 1 ? btn(`Применить все замены (${all.length})`, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await replace(j, run, all);
      self.disabled = false;
    }, 'btn-small') : null;
    return h('div', {class: 'stack'}, head, note, undoNote(j, run),
      h('div', {class: 'alert warn'}, `Цвет ${a.layers.length} из ${a.layers_total} слоёв файла ушёл от обещанного больше чем на ${num(a.visible_de, 0)} ΔE (${percent(a.area_share)} площади).`
        + ' Выгравированный файл не меняется; замена правит только работу, её можно отменить.'),
      a.approximate ? h('p', {class: 'small muted'}, 'Файл создан до того, как работа стала запоминать обещанные цвета: «обещано» восстановлено по слоям работы, какими они были при выгрузке.') : null,
      every,
      a.layers.map((l) => h('div', {class: 'stack vw-drift'},
        h('div', {class: 'vw-line'}, h('span', {}, rgb(l.was_srgb, 'обещано'), l.missing ? ' → цвет больше не измерен' : [' → ', rgb(l.now_srgb, 'сейчас')], ` ${l.name}`),
          h('span', {class: 'small vw-bad'}, l.delta_e == null ? sq(l.area_mm2) : `ΔE ${num(l.delta_e, 1)} · ${sq(l.area_mm2)}`)),
        ...l.proposals.filter((p) => p.entry_id).map((p) => replacement(j, p, run)),
        l.proposals.some((p) => !p.entry_id) ? h('p', {class: 'small muted'}, 'Для остальных исходных цветов этого слоя ближе измеренного цвета нет.') : null)));
  }

  /** Вкладка «Результат»: итог последней гравировки и цвета после новых измерений. ``run`` отправляет правку раскраски в очередь экрана. */
  function view(j, run) {
    seen.set(j.id, j.undo);
    return h('div', {class: 'stack'}, resultBlock(j), driftBlock(j, run));
  }

  /** Метка вкладки: сколько слоёв работы ушло от обещанного. */
  function tabLabel(j) {
    return j.attention && j.attention.layers.length ? `Результат · ⚠ ${j.attention.layers.length}` : 'Результат';
  }

  // ---- списки ---------------------------------------------------------------------------------------------------------------------

  /** Строки карточки работы в списке работ: что изменилось и чем кончилась последняя гравировка. */
  function cardLines(w) {
    const lines = [];
    if (w.attention && w.attention.layers) lines.push(h('p', {class: 'small vw-bad'}, `⚠ Цвет ${w.attention.layers} слоёв ушёл от обещанного файлом (${percent(w.attention.area_share)} площади)`));
    if (w.review) {
      lines.push(h('p', {class: 'small'}, w.review.matched
        ? `Результат гравировки (${w.review.photo_name}): ΔE ${num(w.review.mean_delta_e, 1)}, заметно отличаются ${w.review.beyond_layers} из ${w.review.matched} слоёв`
        : w.review.promise_lost ? `Фото ${w.review.photo_name}: обещанное файлом не сохранилось, сравнения нет`
        : `Фото ${w.review.photo_name}: слои не совпали с файлом этой работы`));
    }
    return lines;
  }

  /** Блок в отчёте по фото: вывод, записанный в работу, к которой фото относится. */
  function reportCard(wr) {
    if (!wr) return null;
    const s = wr.review.summary;
    return h('div', {class: 'card stack'}, h('h3', {}, `Вывод по работе «${wr.work}»`),
      s.matched ? h('p', {}, `Совпало слоёв ${s.matched} из ${s.promised} ожидаемых; средняя разница ${num(s.mean_delta_e, 1)} ΔE; заметно отличаются ${s.beyond_layers} слоёв `
        + `(${percent(s.area_share_beyond)} площади).`) : h('p', {}, wr.review.promise_lost ? LOST : 'Ни один слой этого файла не совпал по настройкам с файлом работы.'),
      wr.review.basis ? h('p', {class: 'small'}, Lifecycle.basisNote(wr.review.basis)) : null,
      ...wr.review.notes.map((n) => h('p', {class: 'small muted'}, (NOTE[n.code] || (() => n.code))(n))),
      ...(wr.review.photo || []).map(photoResult),
      h('div', {class: 'row'}, link('/vector?plan=' + wr.plan_id, 'Открыть работу: сравнение и замены')));
  }

  return {view, tabLabel, cardLines, reportCard};
})();
