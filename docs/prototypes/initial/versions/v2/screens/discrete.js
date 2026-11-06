(function () {
  'use strict';
  const h = App.h, KEY = 'titanium.discrete.ui.v1';
  const stages = ['Валидировано', 'Производственное'];
  const all = entity => DB.list(entity, {pageSize: 100000, sort: 'createdAt', dir: 'asc'}).items;
  const link = (label, route) => h('a', {class: 'btn btn-small', href: '#' + route}, label);
  const num = n => Number.isFinite(n) ? n.toLocaleString('ru-RU', {maximumFractionDigits: 2}) : 'Не определено';
  const labText = c => c ? 'Lab ' + [c.L, c.a, c.b].map(num).join(' · ') : 'Нет данных';
  function rgbLab(r, g, b) {
    const linear = v => (v /= 255) <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4);
    [r, g, b] = [r, g, b].map(linear);
    const f = v => v > .008856 ? Math.cbrt(v) : 7.787 * v + 16 / 116;
    const x = f((r * .4124564 + g * .3575761 + b * .1804375) / .95047);
    const y = f(r * .2126729 + g * .7151522 + b * .072175);
    const z = f((r * .0193339 + g * .119192 + b * .9503041) / 1.08883);
    return {L: 116 * y - 16, a: 500 * (x - y), b: 200 * (y - z)};
  }
  function cssLab(c) { return c ? 'lab(' + c.L + '% ' + c.a + ' ' + c.b + ')' : '#e2e5eb'; }
  function swatch(c) { return h('span', {class: 'swatch', style: {background: cssLab(c)}, role: 'img', 'aria-label': labText(c)}); }
  function prediction(p) {
    return h('div', {class: 'discrete-metrics'},
      h('span', {}, 'Уверенность: ', num(p.confidence), ' / 1'),
      h('span', {}, 'Ожидаемая ошибка ΔE: ', num(p.expectedDeltaE)),
      h('span', {}, 'Стабильность: ', p.stability?.assessed ? 'Оценена; дисперсия ' + num(p.stability.variance) : 'Не оценена'));
  }
  function parameters(p) {
    if (!p) return 'Нет данных';
    return 'Мощность ' + num(p.power) + ' % · Частота ' + num(p.frequency) + ' кГц · Скорость ' + num(p.speed) + ' мм/с · Импульс ' + num(p.pulseDuration) + ' нс · Интервал ' + num(p.lineInterval) + ' мм · Проходы ' + num(p.passes);
  }
  App.addStyles(`
    .discrete-screen{display:flex;flex-direction:column;gap:24px}.discrete-screen .toolbar{margin:0}.discrete-previews{display:grid;grid-template-columns:1fr 1fr;gap:24px}.discrete-picture{height:260px;border:1px solid var(--line);border-radius:12px;background:repeating-conic-gradient(#f0f1f4 0% 25%,#fff 0% 50%) 50%/20px 20px;display:flex;align-items:center;justify-content:center;overflow:hidden;position:relative}.discrete-picture img,.discrete-picture canvas{max-width:100%;max-height:100%;object-fit:contain}.discrete-metrics{display:flex;flex-direction:column;gap:4px;font-size:13px}.discrete-colour{display:flex;align-items:center;gap:10px}.discrete-screen .table{min-width:950px}.discrete-screen .table td{max-width:320px}.discrete-screen .table .btn{margin:3px 3px 3px 0}.discrete-options{display:grid;gap:12px}.discrete-option{border:1px solid var(--line);border-radius:12px;padding:14px}.discrete-option:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}.discrete-target{position:absolute;inset:0;pointer-events:none;border:3px solid var(--accent);border-radius:12px}.discrete-footer{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}.discrete-legend{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;margin-top:12px}.discrete-screen .field{margin-bottom:0}.discrete-screen .alert p:last-child{margin:0}@media(max-width:800px){.discrete-previews{grid-template-columns:1fr}.discrete-picture{height:220px}}
  `);
  App.register({id: 'discrete', route: '/artwork', title: 'Цветная гравировка', render(ctx) {
    const host = h('div', {class: 'discrete-screen'});
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (_) {}
    let plan = null, busy = false, selected = null, source = null, lastAction = null;
    let profileId = '', threshold = '4', markers = true, message = '', error = '';
    const persist = () => {
      try { localStorage.setItem(KEY, JSON.stringify({planId: plan?.id || null, profileId, threshold, markers, source})); }
      catch (_) { App.toast('Не удалось сохранить предпросмотр в браузере. Он доступен до закрытия страницы.', 'warning'); }
    };
    function eligible(k, includeQuestionable) {
      return k.profileId === profileId && stages.includes(k.stage) && (!k.questionable || includeQuestionable?.includes(k.id)) && k.lab && Number.isFinite(k.confidence) && Number.isFinite(k.expectedDeltaE) && k.stability?.assessed;
    }
    async function act(label, fn) {
      if (busy) return;
      busy = true; error = ''; message = label; lastAction = () => act(label, fn); draw();
      try { await new Promise(resolve => setTimeout(resolve, 360)); await fn(); persist(); }
      catch (e) { error = e.message || 'Не удалось выполнить сопоставление'; }
      finally { busy = false; message = ''; draw(); }
    }
    function match() {
      const t = threshold.trim() === '' ? NaN : Number(threshold);
      if (!Number.isFinite(t) || t < 0) { error = 'Введите неотрицательный порог ΔE'; draw(); return; }
      if (!source || !profileId) return;
      return act('Сопоставляем цвета…', () => {
        plan = DB.matchArtwork({planId: plan?.profileId === profileId ? plan.id : undefined, profileId, image: source.image, colors: source.colors, deltaThreshold: t, markers, name: source.image.name + ' — цветная гравировка'});
        if (plan.markers !== markers) plan = DB.setPlanMarkers(plan.id, markers);
      });
    }
    function chooseReplacement(color) {
      const palette = all('Запись знания').filter(k => eligible(k, plan.allowedQuestionableIds));
      let chosen = color.prediction?.knowledgeId || null;
      const notice = h('p', {class: 'field-error', role: 'alert'});
      const body = h('div', {class: 'stack'}, h('p', {}, 'Исходный цвет: ', labText(color.lab)), notice);
      if (!palette.length) body.append(h('p', {}, 'Нет допустимых цветов для замены.'));
      palette.forEach(k => body.append(h('label', {class: 'check discrete-option'}, h('input', {type: 'radio', name: 'discrete-replacement', value: k.id, checked: chosen === k.id, onChange: () => {chosen = k.id; notice.textContent = '';}}), h('div', {class: 'stack'}, h('div', {class: 'discrete-colour'}, swatch(k.lab), h('div', {}, labText(k.lab), h('div', {class: 'muted'}, k.stage, k.questionable ? ' · Под вопросом' : ''))), h('div', {}, parameters(k.parameters)), prediction(k), h('div', {}, 'Фактическое отклонение ΔE: ', num(DB.deltaE(color.lab, k.lab)))))));
      App.modal({title: 'Заменить цвет', body, actions: [
        {label: 'Отмена', onClick: api => api.close()},
        {label: 'Применить замену', kind: 'primary', disabled: !palette.length, onClick: api => {
          if (!chosen) {notice.textContent = 'Выберите цвет титана'; return;}
          api.close(); act('Сопоставляем цвета…', () => {plan = DB.resolveArtworkColor(plan.id, color.id, 'replace', chosen);});
        }}
      ]});
    }
    function questionable() {
      if (!plan) return;
      const entries = all('Запись знания').filter(k => k.profileId === profileId && k.stage === 'Производственное' && k.questionable);
      const chosen = new Set(plan.allowedQuestionableIds || []);
      const body = h('div', {class: 'stack'}, h('p', {}, 'Разрешение действует только в этом плане. Стадия и флаг записи знания сохраняются.'));
      if (!entries.length) body.append(h('p', {}, 'Нет производственных параметров под вопросом для этой версии профиля.'));
      entries.forEach(k => {
        const observations = (k.doubtObservationIds || []).map(id => DB.get('Наблюдение', id)).filter(Boolean);
        body.append(h('div', {class: 'discrete-option stack'}, h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: chosen.has(k.id), onChange: e => e.target.checked ? chosen.add(k.id) : chosen.delete(k.id)}), h('span', {}, labText(k.lab), ' · Производственное · Под вопросом')), h('div', {class: 'discrete-colour'}, swatch(k.lab), h('span', {}, parameters(k.parameters))), prediction(k), h('p', {}, k.doubtReason || 'Причина сомнения не указана'), observations.map(o => h('p', {class: 'text-sm'}, 'Основание ', o.id, ': ', labText(o.lab), ' · ', o.batch || 'Партия: неизвестно')), link('Наблюдения', '/knowledge/' + encodeURIComponent(k.id))));
      });
      App.modal({title: 'Включить параметры под вопросом в этот план', body, actions: [{label: 'Отмена', onClick: api => api.close()}, {label: 'Применить к этому плану', kind: 'primary', onClick: api => {api.close(); act('Сопоставляем цвета…', () => {plan = DB.allowQuestionable(plan.id, [...chosen]);});}}]});
    }
    async function readImage(file) {
      if (!file) return;
      await act('Читаем изображение…', async () => {
        if (!file.type.startsWith('image/')) throw new Error('Не удалось прочитать изображение');
        const url = await new Promise((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('Не удалось прочитать изображение')); reader.readAsDataURL(file);});
        const image = await new Promise((resolve, reject) => {const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('Не удалось прочитать изображение')); img.src = url;});
        const canvas = document.createElement('canvas');
        const ratio = Math.min(1, 640 / Math.max(image.width, image.height));
        canvas.width = Math.max(1, Math.round(image.width * ratio)); canvas.height = Math.max(1, Math.round(image.height * ratio));
        const c = canvas.getContext('2d', {willReadFrequently: true}); c.drawImage(image, 0, 0, canvas.width, canvas.height);
        const pixels = c.getImageData(0, 0, canvas.width, canvas.height), bins = new Map();
        for (let i = 0; i < pixels.data.length; i += 4) {
          const d = pixels.data; if (d[i + 3] < 128) continue;
          const key = [d[i], d[i + 1], d[i + 2]].map(v => Math.min(255, Math.round(v / 32) * 32)).join(',');
          bins.set(key, (bins.get(key) || 0) + 1);
        }
        if (!bins.size) throw new Error('Изображение не содержит непрозрачных областей для гравировки');
        const colors = [...bins].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([key, count], i) => ({id: 'source-color-' + (i + 1), lab: rgbLab(...key.split(',').map(Number)), rgb: key.split(',').map(Number), pixelCount: count}));
        source = {image: {name: file.name, type: file.type, demo: true}, url: canvas.toDataURL('image/png'), colors};
        plan = null; selected = null;
      });
      if (!error) match();
    }
    function preview(converted) {
      const box = h('div', {class: 'discrete-picture', 'aria-label': converted ? 'Предпросмотр гравировки' : 'Исходное изображение'});
      if (!source) {box.append(h('p', {class: 'muted'}, 'Изображение не выбрано')); return box;}
      if (!source.url) {
        const strips = h('div', {style: {display: 'flex', width: '85%', height: '65%', borderRadius: '16px', overflow: 'hidden'}});
        source.colors.forEach(color => {
          const m = plan?.matches?.find(m => m.id === color.id), excluded = converted && m?.status === 'Исключён';
          strips.append(h('button', {type: 'button', disabled: busy, 'aria-label': 'Выбрать исходный цвет ' + labText(color.lab), style: {flex: '1', border: selected === color.id ? '4px solid #0066d6' : '1px solid #ffffff88', background: excluded ? 'repeating-linear-gradient(45deg,#eee 0 6px,#ccc 6px 8px)' : cssLab(converted && m?.prediction?.lab ? m.prediction.lab : color.lab)}, onClick: () => {selected = color.id; draw();}}));
        }); box.append(strips); return box;
      }
      const canvas = document.createElement('canvas');
      const image = new Image(); image.onload = () => {
        canvas.width = image.width; canvas.height = image.height;
        const c = canvas.getContext('2d'); c.drawImage(image, 0, 0);
        if (!converted && !selected) return;
        const pixels = c.getImageData(0, 0, canvas.width, canvas.height);
        for (let i = 0; i < pixels.data.length; i += 4) {
          const d = pixels.data; if (d[i + 3] < 128) continue;
          let best = source.colors[0], distance = Infinity;
          source.colors.forEach(color => {const v = color.rgb; if (!v) return; const dd = (v[0] - d[i]) ** 2 + (v[1] - d[i + 1]) ** 2 + (v[2] - d[i + 2]) ** 2; if (dd < distance) {distance = dd; best = color;}});
          const m = plan?.matches?.find(m => m.id === best.id);
          if (converted && m?.status === 'Исключён') {const shade = ((Math.floor(i / 4 / canvas.width / 6) + Math.floor(i / 4 % canvas.width / 6)) % 2) ? 215 : 245; d[i] = d[i + 1] = d[i + 2] = shade;}
          else if (converted && m?.prediction?.lab) {
            const rgb = labRgb(m.prediction.lab); d[i] = rgb[0]; d[i + 1] = rgb[1]; d[i + 2] = rgb[2];
          }
          if (selected && best.id !== selected) {d[i] = d[i] * .25 + 240 * .75; d[i + 1] = d[i + 1] * .25 + 240 * .75; d[i + 2] = d[i + 2] * .25 + 240 * .75;}
        } c.putImageData(pixels, 0, 0);
      }; image.src = source.url; box.append(canvas); return box;
    }
    function draw() {
      const profiles = all('Профиль лазера');
      const profile = profiles.find(p => p.id === profileId);
      const model = all('Модель цветового пространства').filter(m => m.profileId === profileId).at(-1);
      const matches = plan?.matches || [], unresolved = matches.filter(c => c.status === 'Недостижим').length;
      const active = matches.filter(c => c.status !== 'Исключён');
      const palette = all('Запись знания').filter(k => eligible(k, plan?.allowedQuestionableIds));
      const stale = !!plan && (plan.profileId !== profileId || threshold.trim() === '' || Number(threshold) !== plan.deltaThreshold);
      const ready = !!plan && !stale && active.length > 0 && !unresolved && active.every(c => c.prediction?.available && Number.isFinite(c.prediction.confidence) && Number.isFinite(c.prediction.expectedDeltaE) && c.prediction.stability?.assessed);
      host.replaceChildren();
      const upload = h('input', {type: 'file', accept: 'image/*', class: 'sr-only', tabindex: '-1', onChange: e => readImage(e.target.files[0])});
      const select = h('select', {id: 'discrete-profile', disabled: busy || !profiles.length, onChange: e => {profileId = e.target.value; plan = null; selected = null; persist(); draw(); if (source) match();}}, profiles.map(p => h('option', {value: p.id, selected: p.id === profileId}, 'Версия ' + p.version + ' · ' + p.name)));
      const input = h('input', {id: 'discrete-threshold', type: 'number', min: '0', step: 'any', value: threshold, disabled: busy, 'aria-invalid': threshold.trim() === '' || !Number.isFinite(Number(threshold)) || Number(threshold) < 0 ? 'true' : 'false', onInput: e => {threshold = e.target.value; persist(); const create = host.querySelector('[data-create]'); if (create) create.disabled = true;}, onChange: () => draw()});
      host.append(h('section', {class: 'card stack'}, h('div', {class: 'discrete-footer'}, h('div', {}, h('h2', {}, 'От рисунка к палитре титана'), h('p', {class: 'muted'}, 'Сопоставьте цвета и явно разрешите каждую недостижимую цель.')), h('button', {class: 'btn', type: 'button', disabled: busy, onClick: () => upload.click()}, 'Выбрать изображение'), upload), h('div', {class: 'toolbar'}, h('div', {class: 'field', style: {flex: '2'}}, h('label', {for: 'discrete-profile'}, 'Версия профиля'), select), h('div', {class: 'field'}, h('label', {for: 'discrete-threshold'}, 'Порог ΔE'), input), h('button', {type: 'button', class: 'btn', disabled: busy || !source || !profile, onClick: match}, 'Сопоставить цвета')), h('p', {class: 'text-sm muted'}, 'Модель: ', model?.version || 'Нет данных', ' · Профиль: ', profile ? 'версия ' + profile.version : 'Не выбран')));
      if (busy) host.append(h('div', {class: 'alert', role: 'status', 'aria-live': 'polite'}, message));
      if (error) host.append(h('div', {class: 'alert alert-danger', role: 'alert'}, h('p', {}, error), lastAction ? h('button', {class: 'btn', disabled: busy, onClick: lastAction}, 'Повторить') : null));
      if (!profile) host.append(h('div', {class: 'permission-restricted'}, 'Сначала настройте профиль лазера. ', link('Профили', '/profiles')));
      if (!source) {
        host.append(h('section', {class: 'empty-state'}, h('h2', {}, 'Добавьте изображение для цветной гравировки'), h('p', {}, 'Выберите локальный рисунок. Измерительная фотография и эталон для этого шага не нужны.')));
        assumptions(); return;
      }
      host.append(h('section', {class: 'discrete-previews'}, h('div', {class: 'card'}, h('h2', {}, 'Исходное изображение'), preview(false), h('p', {class: 'text-sm muted', style: {marginTop: '12px'}}, source.image.name)), h('div', {class: 'card'}, h('h2', {}, 'Предпросмотр гравировки'), preview(true), h('div', {class: 'discrete-legend'}, h('span', {}, 'Штриховка — исключённые области'), h('span', {}, 'Недостижимые цвета сохраняют исходный цвет')))));
      if (!palette.length) host.append(h('div', {class: 'alert alert-warning'}, 'Нет валидированных или производственных цветов для этой версии профиля'));
      if (stale) host.append(h('p', {class: 'alert alert-warning'}, 'Порог ΔE изменён. Сопоставьте цвета повторно.'));
      if (plan) {
        const targets = all('Целевой цвет').filter(t => t.sourcePlanId === plan.id);
        host.append(h('div', {class: 'discrete-footer'}, h('div', {}, h('strong', {}, 'Нерешённые недостижимые цвета: ', unresolved), h('div', {class: 'muted text-sm'}, 'Передано целей планировщику: ', targets.length)), link('Цели экспериментов', '/designer?profile=' + encodeURIComponent(profileId) + '&plan=' + encodeURIComponent(plan.id))));
        const rows = matches.map(color => {
          const p = color.prediction;
          return h('tr', {class: selected === color.id ? 'selected' : ''},
            h('td', {}, h('button', {class: 'btn btn-ghost', type: 'button', disabled: busy, 'aria-pressed': selected === color.id, onClick: () => {selected = selected === color.id ? null : color.id; draw();}}, swatch(color.lab), h('span', {}, labText(color.lab)))),
            h('td', {}, h('span', {class: 'badge ' + (color.status === 'Недостижим' ? 'badge-warning' : color.status === 'Исключён' ? '' : 'badge-success')}, color.status)),
            h('td', {}, p?.available && color.status !== 'Исключён' ? h('div', {class: 'stack'}, h('div', {class: 'discrete-colour'}, swatch(p.lab), h('span', {}, labText(p.lab))), h('span', {}, 'Фактическое отклонение ΔE: ', num(p.deltaE)), prediction(p), h('span', {class: 'text-sm'}, p.stage, p.questionable ? ' · Под вопросом' : ''), h('span', {class: 'text-sm muted'}, parameters(p.parameters))) : color.status === 'Исключён' ? 'Области убраны из гравировки' : 'Недостаточно данных для прогноза'),
            h('td', {}, color.status === 'Исключён' ? h('button', {class: 'btn btn-small', type: 'button', disabled: busy || stale, onClick: () => act('Сопоставляем цвета…', () => {plan = DB.resolveArtworkColor(plan.id, color.id, 'restore');})}, 'Вернуть в сопоставление') : [h('button', {class: 'btn btn-small', type: 'button', disabled: busy || stale, onClick: () => chooseReplacement(color)}, 'Заменить'), h('button', {class: 'btn btn-small', type: 'button', disabled: busy || stale, onClick: () => act('Сопоставляем цвета…', () => {plan = DB.resolveArtworkColor(plan.id, color.id, 'exclude');})}, 'Исключить')])
          );
        });
        host.append(h('section', {class: 'card stack'}, h('h2', {}, 'Соответствия цветов'), h('div', {class: 'table-wrap'}, h('table', {class: 'table'}, h('thead', {}, h('tr', {}, ['Исходный цвет', 'Состояние', 'Цвет титана и прогноз', 'Решение'].map(t => h('th', {scope: 'col'}, t)))), h('tbody', {}, rows)))));
        host.append(h('section', {class: 'card stack'}, h('h2', {}, 'Параметры этого плана'), h('button', {class: 'btn', type: 'button', disabled: busy || stale, onClick: questionable}, 'Включить параметры под вопросом в этот план'), h('p', {class: 'text-sm'}, 'Разрешённые записи: ', plan.allowedQuestionableIds?.length ? plan.allowedQuestionableIds.map(id => link(labText(DB.get('Запись знания', id)?.lab), '/knowledge/' + encodeURIComponent(id))) : 'Нет'), h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: markers, disabled: busy, onChange: e => {const next = e.target.checked; act('Сохраняем маркеры…', () => {plan = DB.setPlanMarkers(plan.id, next); markers = next;});}}), h('span', {}, 'Регистрационные маркеры')), h('p', {class: 'text-sm muted'}, markers ? 'Маркеры и машинный идентификатор «' + (plan.markerGeometry?.machineId || plan.id) + '» размещаются вне изображения.' : 'Маркеры и машинный идентификатор выключены.')));
        host.append(h('section', {class: 'card discrete-footer'}, h('p', {role: 'status', style: {margin: '0'}}, unresolved ? 'Замените или исключите все недостижимые цвета перед созданием плана' : !active.length ? 'В плане не осталось областей для гравировки' : ready ? 'Все цвета обработаны. План можно создать' : 'Для создания плана выполните сопоставление с полными показателями прогноза'), h('button', {class: 'btn btn-primary', type: 'button', 'data-create': 'true', disabled: busy || !ready, onClick: () => act('Создаём план…', () => {const result = DB.finalizeArtwork(plan.id); plan = result; persist(); App.navigate('/plans/' + encodeURIComponent(result.id));})}, 'Создать план')));
      }
      assumptions();
    }
    function assumptions() {
      host.append(h('details', {class: 'card'}, h('summary', {}, 'Допущения экрана'), h('p', {class: 'text-sm muted', style: {marginTop: '12px'}}, 'Для демонстрации рисунок уменьшается до 640 пикселей по большей стороне; выделяются до восьми основных цветов с округлением RGB и приближённым переводом в Lab. Каждый непрозрачный пиксель относится к ближайшему основному цвету. Это подготовка демонстрационного предпросмотра, а не физически точное цветоделение. Геометрию экспортных слоёв демонстрирует общий backend. Предпросмотр и черновик сохраняются локально. При открытии существующего плана без сохранённого изображения показана схема цветовых областей. Удаление планов на этом экране требованиями не предусмотрено.')));
    }
    return App.load(() => {
      const profiles = all('Профиль лазера');
      const requested = ctx.query.get('plan') || ctx.query.get('id');
      const existing = requested ? DB.get('План гравировки', requested) : saved.planId ? DB.get('План гравировки', saved.planId) : null;
      if (!ctx.proto.empty && existing?.mode === 'Цветная гравировка') {
        plan = existing; profileId = plan.profileId; threshold = String(plan.deltaThreshold ?? 4); markers = plan.markers;
        source = saved.planId === plan.id && saved.source ? saved.source : plan.sourceColors?.length ? {image: plan.image || {name: 'Сохранённый рисунок'}, colors: plan.sourceColors} : null;
        if (!source) plan = null;
      }
      profileId = profileId || (profiles.some(p => p.id === saved.profileId) ? saved.profileId : profiles[0]?.id || '');
      if (!plan && !ctx.proto.empty) {source = saved.source || null; threshold = String(saved.threshold ?? 4); markers = saved.markers !== false;}
      if (ctx.proto.empty) {source = null; plan = null;}
      draw(); return host;
    });
  }});
  function labRgb(c) {
    const fy = (c.L + 16) / 116, fx = fy + c.a / 500, fz = fy - c.b / 200;
    const inv = v => v ** 3 > .008856 ? v ** 3 : (v - 16 / 116) / 7.787;
    const x = inv(fx) * .95047, y = inv(fy), z = inv(fz) * 1.08883;
    return [x * 3.2404542 - y * 1.5371385 - z * .4985314, -x * .969266 + y * 1.8760108 + z * .041556, x * .0556434 - y * .2040259 + z * 1.0572252].map(v => Math.round(255 * Math.max(0, Math.min(1, v <= .0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - .055))));
  }
})();
