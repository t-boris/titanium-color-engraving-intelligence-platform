/* Research session: a compact conversation beside the actual laser, stock and LightBurn artifacts. */
'use strict';
(() => {
  const {h, btn, field, link, get, post, del, toast, fail, pill, confirmBox} = App;
  const goalName = (goals, id) => goals.find((item) => item.id === id)?.name || id;
  const option = (value, label) => h('option', {value}, label);
  const SETTING_NAMES = {power: 'Мощность, %', frequency: 'Частота, кГц', speed: 'Скорость, мм/с', pulse_width: 'Импульс, нс',
    line_interval: 'Шаг линий, мм', passes: 'Проходы', global_passes: 'Глобальные проходы', max_width_mm: 'Предел ширины, мм',
    max_height_mm: 'Предел высоты, мм', matrix: 'Матрица', x_axis: 'Ось X', y_axis: 'Ось Y', x_min: 'X от', x_max: 'X до', x_count: 'Число по X',
    y_min: 'Y от', y_max: 'Y до', y_count: 'Число по Y', geometry: 'Образец', registration: 'Метки', patch_size_mm: 'Размер образца, мм',
    patches: 'Образцы', recipes: 'Рецепты', widths_mm: 'Ширины, мм', task: 'Задача'};
  function proposalSettings(settings) {
    const hidden = new Set(['research_session_id', 'research_goal', 'source_pair_id']);
    const show = (value) => value == null ? 'не задано' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    return h('dl', {class: 'facts'}, ...Object.entries(settings || {}).filter(([key]) => !hidden.has(key)).map(([key, value]) =>
      [h('dt', {}, SETTING_NAMES[key] || key), h('dd', {}, show(value))]));
  }

  /** «Скачать LightBurn»: one press at a time, a failure stays beside the button with a retry (Lifecycle.downloadButton); a plain link where that is not loaded. */
  function downloadLightBurn(plan) {
    const path = `/plans/${plan.id}/export.lbrn2`;
    if (typeof Lifecycle === 'undefined') return h('a', {href: '/api' + path, class: 'btn btn-small'}, 'Скачать LightBurn');
    return Lifecycle.downloadButton(path, `${String(plan.name || 'plate').replace(/[^\w.-]+/g, '_')}.lbrn2`, 'Скачать LightBurn', {cls: 'btn-small'}).el;
  }

  function artifacts(plans) {
    return plans.length ? plans.map((plan) => h('div', {class: 'research-artifact'},
      h('div', {}, link('/plans/' + plan.id, plan.name), pill(({Exported: 'Экспортирован',
        Superseded: 'Заменена', Cancelled: 'Отменена'})[plan.status] || 'Готов')),
      ['Superseded', 'Cancelled'].includes(plan.status) ? null : downloadLightBurn(plan))) :
      [h('p', {class: 'muted small'}, 'Пока нет платы. Опишите критерий и попросите AI предложить тест.')];
  }

  function photoItems(photos) {
    return photos.length ? photos.map((photo) => h('div', {class: 'research-artifact'},
      h('div', {}, link(photo.status === 'Accepted' ? '/analysis/' + photo.id : '/ingest?pair=' + photo.id,
        `Фото №${photo.id} · ${photo.photo_name}`),
      pill(photo.status === 'Accepted' ? 'Принято' : 'Проверить', photo.status === 'Accepted' ? 'ok' : 'warn')))) :
      [h('p', {class: 'muted small'}, 'Для этой платы пока нет фотографий.')];
  }

  function insightItems(insights) {
    return insights.slice(0, 5).map((item) => h('p', {class: 'small'}, item.claim,
      ' · ', item.evidence_pair_ids.map((id) => link('/analysis/' + id, `№${id}`))));
  }

  function messageNode(message, createProposal = null) {
    const trace = message.tool_trace || [];
    const created = trace.filter((item) => ['create_test', 'replace_pending_test'].includes(item.tool) && item.result?.plan_id);
    const pairs = [...new Set(trace.filter((item) => item.result?.pair_id).map((item) => item.result.pair_id))];
    const previews = trace.map((item, index) => {
      if (item.tool !== 'preview_test' || !item.result?.context_signature || !message.id || !createProposal) return null;
      const p = item.result, size = p.summary?.size_mm, feedback = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
      const create = async () => {
        action.disabled = true; feedback.textContent = 'Создаём тест…';
        try {
          const made = await createProposal(message.id, index, p.pending_plan_id || null);
          feedback.replaceChildren(h('a', {href: made.plan_url}, `Открыть созданную плату №${made.plan_id}`));
          action.hidden = true;
        } catch (e) { feedback.textContent = e.message; action.disabled = false; }
      };
      const action = btn(p.pending_plan_id ? `Заменить плату №${p.pending_plan_id}…` : 'Создать тест', () => {
        if (!p.pending_plan_id) return create();
        return confirmBox('Заменить ожидающую плату', `Плата №${p.pending_plan_id} останется в истории как заменённая; её файл больше нельзя будет выгрузить. Создать новый предложенный тест?`,
          'Заменить и создать', create);
      }, 'primary btn-small', !!p.pending_plan_id && !p.pending_replaceable);
      if (item.created_plan) { action.hidden = true; feedback.append(link(`/plans/${item.created_plan.plan_id}`, `Открыть созданную плату №${item.created_plan.plan_id}`)); }
      return h('div', {class: 'card stack research-proposal'}, h('strong', {}, `Предложение: ${p.name}`),
        h('p', {class: 'small'}, p.description || '', size ? ` · размер ${size.width} × ${size.height} мм` : ' · размер не определён',
          ` · ${p.time_unavailable_reason || 'оценка времени недоступна'}`),
        p.pending_plan_id && !p.pending_replaceable ? h('p', {class: 'alert warn'}, `К плате №${p.pending_plan_id} уже привязано фото: сначала разберите проверку.`) : null,
        h('details', {}, h('summary', {}, 'Настройки предложенного теста'), proposalSettings(p.test_settings),
          h('h4', {}, 'Очистка'), proposalSettings(p.cleanup_settings),
          p.label_settings ? [h('h4', {}, 'Метки'), proposalSettings(p.label_settings)] : null),
        action, feedback);
    });
    return h('article', {class: `research-message ${message.role === 'user' ? 'from-user' : 'from-ai'}`},
      h('small', {}, message.role === 'user' ? 'Вы' : 'AI-исследователь'),
      message.role === 'user' ? (message.content.length > 260 ?
        h('details', {class: 'research-long-message'},
          h('summary', {}, message.content.slice(0, 170).trimEnd() + '…'),
          h('p', {class: 'research-user-text'}, message.content)) :
        h('p', {class: 'research-user-text'}, message.content)) : App.renderMarkdown(message.content),
      created.length || pairs.length ? h('div', {class: 'research-message-links'},
        ...created.map((item) => h('a', {href: item.result.download_url, class: 'btn btn-small'},
          `Скачать плату №${item.result.plan_id}`)),
        ...pairs.map((pairId) => link('/analysis/' + pairId, `Проверка №${pairId}`))) : null, previews);
  }

  App.register({id: 'research', async render(ctx) {
    const [devices, stocks, goals, sessions] = await Promise.all([
      get('/devices'), get('/materials?limit=1'), get('/application-goals'), get('/research/sessions')]);
    const hasMaterials = (Array.isArray(stocks) ? stocks.length : stocks.all) > 0;     // the records themselves are chosen in the picker, a page at a time
    const requested = Number(ctx.arg);
    const selected = sessions.find((item) => item.id === requested) || sessions[0];
    const active = selected ? await get('/research/sessions/' + selected.id) : null;
    const list = h('section', {class: 'card research-sidebar'},
      h('div', {class: 'research-panel-head'}, h('h3', {}, 'Исследования'), pill(sessions.length)),
      h('div', {class: 'research-session-list'},
        ...sessions.map((item) => h('a', {href: '#/research/' + item.id,
          class: `research-session-link ${item.id === active?.id ? 'active' : ''}`},
          h('strong', {}, goalName(goals, item.goal)),
          h('span', {}, item.target),
          h('small', {}, `${item.device_name} · ${item.lens_name} · ${item.material_name}`)))),
      active ? btn('Удалить исследование', () => confirmBox('Удалить исследование',
        'Исследование исчезнет из списка. Платы, фотографии и измерения останутся в «Экспериментах»; история разговора сохранится в локальной базе.',
        'Удалить исследование', async () => {
          await del(`/research/sessions/${active.id}`);
          toast('Исследование удалено из списка', 'ok');
          if (location.hash === '#/research') App.render();
          else App.go('/research');
        }), 'btn-small danger research-delete') : null);

    const form = Forms.create();
    const deviceSelect = h('select', {required: true}, devices.map((item) => option(item.id, [item.name, item.lens?.name].filter(Boolean).join(' · '))));
    const materialSelect = MaterialPicker.create({initial: 'recent', name: 'Материал и заготовка'});
    const goalSelect = h('select', {required: true}, goals.map((item) => option(item.id, item.name)));
    const targetInput = h('textarea', {rows: '2', placeholder: 'Например: читаемый чёрный текст высотой 1 мм на Grade 2 при минимальном времени обработки'});
    const deviceField = form.add('device', 'Лазер и линза', deviceSelect, {required: true, help: 'на лазере должна стоять линза'});
    const materialField = form.add('material', 'Материал и заготовка', materialSelect, {required: true,
      read: () => (materialSelect.value ? {ok: true, value: Number(materialSelect.value)} : {ok: false, message: 'Выберите заготовку: конкретную партию или лист'})});
    const goalField = form.add('goal', 'Задача', goalSelect, {required: true});
    // research.create_session: the target is 4 to 600 characters; a longer text is refused with its length, not cut short
    const targetField = form.add('target', 'Что считаем успехом', targetInput, {required: true, minLength: 4, maxLength: 600});
    const createButton = btn('Начать исследование', async () => {
      const v = form.collect();
      if (!v) return;
      createButton.disabled = true;
      try {
        const session = await post('/research/sessions', {device_id: Number(v.device), material_id: v.material, goal: v.goal, target: v.target});
        toast('Исследование создано', 'ok');
        App.go('/research/' + session.id);
      } catch (error) { form.fail(error); createButton.disabled = false; }
    }, 'primary', !devices.length || !hasMaterials);
    const startPanel = h('details', {class: 'card research-new', open: !active},
      h('summary', {}, 'Новое исследование'),
      h('div', {class: 'research-start-grid'}, deviceField, materialField, goalField),
      targetField, form.error,
      h('div', {class: 'row'}, createButton));
    if (!active) return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI-исследователь'),
        h('p', {class: 'sub'}, 'Цель → компактный тест → LightBurn → RAW-фото → вывод'))),
      startPanel, list);

    const planBox = h('div', {class: 'research-artifacts'}, ...artifacts(active.plans));
    async function createProposal(messageId, index, replacePlanId) {
      const made = await post(`/research/sessions/${active.id}/proposals/${messageId}/${index}/create`, {replace_plan_id: replacePlanId});
      try { const updated = await get(`/research/sessions/${active.id}`); planBox.replaceChildren(...artifacts(updated.plans)); }
      catch (_) { /* The created plate is still linked in the message. */ }
      return made;
    }
    const photoBox = h('div', {class: 'research-artifacts'}, ...photoItems(active.photos || []));
    const insightContent = h('div', {}, ...insightItems(active.insights));
    const insightBox = h('details', {hidden: !active.insights.length},
      h('summary', {}, 'Сохранённые выводы'), insightContent);
    const memoryContent = h('div', {}, active.memory ? App.renderMarkdown(active.memory.summary) : null);
    const memoryBox = h('details', {class: 'research-memory', hidden: !active.memory},
      h('summary', {}, 'Память исследования'), memoryContent);
    const scopeCount = h('span', {}, `${active.insights.length} выводов · ${active.plans.length} плат · ${(active.photos || []).length} фото`);
    const chatBody = h('div', {class: 'research-chat-body', role: 'log', 'aria-live': 'polite'},
      ...active.messages.map((message) => messageNode(message, createProposal)));
    if (active.has_older_messages && active.messages.length) {
      let oldest = active.messages[0].id;
      const olderButton = btn('Показать предыдущие сообщения', async () => {
        olderButton.disabled = true;
        try {
          const page = await get(`/research/sessions/${active.id}/messages?before=${oldest}`);
          const previousHeight = chatBody.scrollHeight;
          const fragment = document.createDocumentFragment();
          page.messages.forEach((message) => fragment.append(messageNode(message, createProposal)));
          chatBody.insertBefore(fragment, olderButton.nextSibling);
          if (page.messages.length) oldest = page.messages[0].id;
          if (!page.has_older_messages) olderButton.remove();
          chatBody.scrollTop += chatBody.scrollHeight - previousHeight;
        } catch (error) { fail(error); }
        finally { olderButton.disabled = false; }
      }, 'btn-small research-more');
      chatBody.prepend(olderButton);
    }
    // The thread lives in SQLite. After a fresh render, show the most recent turn rather than the first one.
    requestAnimationFrame(() => { if (chatBody.isConnected) chatBody.scrollTop = chatBody.scrollHeight; });
    if (!active.messages.length) chatBody.append(h('p', {class: 'muted small'},
      'Спросите, что уже известно, или попросите предложить тест. Создание платы подтверждается отдельно под предложением.'));
    const input = h('textarea', {rows: '2', maxlength: '4000', 'aria-label': 'Сообщение AI-исследователю (не больше 4000 символов)',
      placeholder: 'Например: какие линии уже видны? Предложи следующий компактный тест и объясни, что он выяснит.'});
    let busy = false;
    const send = async (suggested, advisory = false) => {
      if (busy) return;
      const value = String(suggested || input.value).trim();
      if (!value) return;
      busy = true; sendButton.disabled = true; sendButton.textContent = 'Анализируем…';
      chatBody.append(messageNode({role: 'user', content: value}),
        h('p', {class: 'research-thinking muted small'}, 'AI изучает данные и может вызвать инструменты…'));
      chatBody.scrollTop = chatBody.scrollHeight;
      input.value = '';
      try {
        const result = await post(`/research/sessions/${active.id}/messages`, {message: value, advisory});
        chatBody.querySelector('.research-thinking')?.remove();
        const saved = result.session.messages[result.session.messages.length - 1];
        chatBody.append(messageNode(saved && saved.role === 'assistant' ? saved : {role: 'assistant', content: result.text, tool_trace: result.tool_trace}, createProposal));
        planBox.replaceChildren(...artifacts(result.session.plans));
        photoBox.replaceChildren(...photoItems(result.session.photos || []));
        insightContent.replaceChildren(...insightItems(result.session.insights));
        insightBox.hidden = !result.session.insights.length;
        memoryContent.replaceChildren(result.session.memory ? App.renderMarkdown(result.session.memory.summary) : h('span'));
        memoryBox.hidden = !result.session.memory;
        scopeCount.textContent = `${result.session.insights.length} выводов · ${result.session.plans.length} плат · ${(result.session.photos || []).length} фото`;
        chatBody.scrollTop = chatBody.scrollHeight;
      } catch (error) {
        chatBody.querySelector('.research-thinking')?.remove();
        chatBody.append(h('p', {class: 'alert bad', role: 'alert'}, error.message));
        input.value = value;
        fail(error);
      } finally { busy = false; sendButton.disabled = false; sendButton.textContent = 'Отправить'; }
    };
    const sendButton = btn('Отправить', () => send(), 'primary');
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); send(); }
    });
    const targetPreview = active.target.length > 105 ? active.target.slice(0, 102).trimEnd() + '…' : active.target;
    const activePanel = h('section', {class: 'card research-main'},
      h('div', {class: 'research-panel-head'}, h('div', {class: 'research-heading'}, h('h3', {}, goalName(goals, active.goal)),
        h('details', {class: 'research-target'}, h('summary', {title: active.target}, targetPreview),
          h('p', {}, active.target))), pill(active.model, 'ok')),
      h('div', {class: 'research-quick'},
        btn('Что уже известно?', () => send('Что уже известно по этой цели? Укажи номера принятых фото и ограничения выводов.', true), 'btn-small'),
        btn('Объяснить результат', () => send('Разбери последнюю принятую фото-проверку: что выяснили о параметрах и каковы ограничения? Укажи источники.', true), 'btn-small'),
        btn('Предложить тест', () => send('Предложи самый полезный компактный следующий тест. Назови гипотезу, критерий успеха и площадь; проверь его через preview_test.', true), 'btn-small')),
      chatBody,
      h('div', {class: 'research-compose'}, input, sendButton, h('small', {class: 'muted'}, '⌘/Ctrl + Enter')));
    const evidencePanel = h('aside', {class: 'card research-evidence'},
      h('h3', {}, 'Лазер и результат'),
      h('div', {class: 'research-scope'},
        h('strong', {}, `${selected.device_name} · ${selected.lens_name}`),
        h('span', {}, [selected.material_name, selected.material_grade].filter(Boolean).join(' · ')),
        scopeCount),
      h('h4', {}, 'Платы и файлы'), planBox,
      h('h4', {}, 'Фотографии и проверки'), photoBox,
      h('div', {class: 'research-evidence-actions'}, link(active.plans.length ?
        `/ingest?plan=${active.plans[0].id}&material=${active.material_id}&device=${active.device_id}&lens=${App.lensParam(active.lens_id)}` : '/ingest', 'Добавить RAW-фото'),
        link('/experiments', 'Все эксперименты')),
      insightBox, memoryBox);
    return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI-исследователь'),
        h('p', {class: 'sub'}, 'Цель → компактный тест → LightBurn → RAW-фото → вывод')),
        link('/experiments', 'Эксперименты')),
      h('div', {class: 'research-layout'}, list, activePanel, evidencePanel), startPanel);
  }});
})();
