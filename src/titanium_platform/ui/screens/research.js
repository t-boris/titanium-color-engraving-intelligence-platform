/* Research session: a compact conversation beside the actual laser, stock and LightBurn artifacts. */
'use strict';
(() => {
  const {h, btn, field, link, get, post, del, toast, fail, pill, confirmBox} = App;
  const goalName = (goals, id) => goals.find((item) => item.id === id)?.name || id;
  const option = (value, label) => h('option', {value}, label);

  function artifacts(plans) {
    return plans.length ? plans.map((plan) => h('div', {class: 'research-artifact'},
      h('div', {}, link('/plans/' + plan.id, plan.name), pill(({Exported: 'Экспортирован',
        Superseded: 'Заменена', Cancelled: 'Отменена'})[plan.status] || 'Готов')),
      ['Superseded', 'Cancelled'].includes(plan.status) ? null :
        h('a', {href: `/api/plans/${plan.id}/export.lbrn2`, class: 'btn btn-small'}, 'Скачать LightBurn'))) :
      [h('p', {class: 'muted small'}, 'Пока нет платы. Опишите критерий и попросите AI предложить или создать тест.')];
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

  function messageNode(message) {
    const trace = message.tool_trace || [];
    const created = trace.filter((item) => ['create_test', 'replace_pending_test'].includes(item.tool) && item.result?.plan_id);
    const pairs = [...new Set(trace.filter((item) => item.result?.pair_id).map((item) => item.result.pair_id))];
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
        ...pairs.map((pairId) => link('/analysis/' + pairId, `Проверка №${pairId}`))) : null);
  }

  App.register({id: 'research', async render(ctx) {
    const [devices, materials, goals, sessions] = await Promise.all([
      get('/devices'), get('/materials'), get('/application-goals'), get('/research/sessions')]);
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

    const deviceSelect = h('select', {required: true}, devices.map((item) => option(item.id, [item.name, item.lens?.name].filter(Boolean).join(' · '))));
    const materialSelect = h('select', {required: true}, materials.map((item) => option(item.id,
      [item.name, item.grade, item.batch].filter(Boolean).join(' · '))));
    const goalSelect = h('select', {required: true}, goals.map((item) => option(item.id, item.name)));
    const targetInput = h('textarea', {rows: '2', maxlength: '600',
      placeholder: 'Например: читаемый чёрный текст высотой 1 мм на Grade 2 при минимальном времени обработки'});
    const createButton = btn('Начать исследование', async () => {
      createButton.disabled = true;
      try {
        const session = await post('/research/sessions', {device_id: Number(deviceSelect.value),
          material_id: Number(materialSelect.value), goal: goalSelect.value, target: targetInput.value});
        toast('Исследование создано', 'ok');
        App.go('/research/' + session.id);
      } catch (error) { fail(error); createButton.disabled = false; }
    }, 'primary', !devices.length || !materials.length);
    const startPanel = h('details', {class: 'card research-new', open: !active},
      h('summary', {}, 'Новое исследование'),
      h('div', {class: 'research-start-grid'}, field('Лазер и линза', deviceSelect),
        field('Материал и заготовка', materialSelect), field('Задача', goalSelect)),
      field('Что считаем успехом', targetInput),
      h('div', {class: 'row'}, createButton));
    if (!active) return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI-исследователь'),
        h('p', {class: 'sub'}, 'Цель → компактный тест → LightBurn → RAW-фото → вывод'))),
      startPanel, list);

    const planBox = h('div', {class: 'research-artifacts'}, ...artifacts(active.plans));
    const photoBox = h('div', {class: 'research-artifacts'}, ...photoItems(active.photos || []));
    const insightContent = h('div', {}, ...insightItems(active.insights));
    const insightBox = h('details', {hidden: !active.insights.length},
      h('summary', {}, 'Сохранённые выводы'), insightContent);
    const memoryContent = h('div', {}, active.memory ? App.renderMarkdown(active.memory.summary) : null);
    const memoryBox = h('details', {class: 'research-memory', hidden: !active.memory},
      h('summary', {}, 'Память исследования'), memoryContent);
    const scopeCount = h('span', {}, `${active.insights.length} выводов · ${active.plans.length} плат · ${(active.photos || []).length} фото`);
    const chatBody = h('div', {class: 'research-chat-body', role: 'log', 'aria-live': 'polite'},
      ...active.messages.map(messageNode));
    if (active.has_older_messages && active.messages.length) {
      let oldest = active.messages[0].id;
      const olderButton = btn('Показать предыдущие сообщения', async () => {
        olderButton.disabled = true;
        try {
          const page = await get(`/research/sessions/${active.id}/messages?before=${oldest}`);
          const previousHeight = chatBody.scrollHeight;
          const fragment = document.createDocumentFragment();
          page.messages.forEach((message) => fragment.append(messageNode(message)));
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
      'Спросите, что уже известно, предложите критерий или попросите создать следующий тест. Созданный файл появится справа.'));
    const input = h('textarea', {rows: '2', maxlength: '4000',
      placeholder: 'Например: какие линии уже видны? Предложи следующий компактный тест и объясни, что он выяснит.'});
    let busy = false;
    const send = async (suggested) => {
      if (busy) return;
      const value = String(suggested || input.value).trim();
      if (!value) return;
      busy = true; sendButton.disabled = true; sendButton.textContent = 'Анализируем…';
      chatBody.append(messageNode({role: 'user', content: value}),
        h('p', {class: 'research-thinking muted small'}, 'AI изучает данные и может вызвать инструменты…'));
      chatBody.scrollTop = chatBody.scrollHeight;
      input.value = '';
      try {
        const result = await post(`/research/sessions/${active.id}/messages`, {message: value});
        chatBody.querySelector('.research-thinking')?.remove();
        chatBody.append(messageNode({role: 'assistant', content: result.text, tool_trace: result.tool_trace}));
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
        btn('Что уже известно?', () => send('Что уже известно по этой цели? Укажи номера принятых фото и ограничения выводов.'), 'btn-small'),
        btn('Разобрать фото', () => send('Разбери последнюю принятую фото-проверку: что выяснили о параметрах, какой вывод сохранить и какой один следующий тест даст максимум пользы?'), 'btn-small'),
        btn('Следующий тест', () => send('Предложи самый полезный компактный следующий тест. Назови гипотезу, критерий успеха и площадь.'), 'btn-small'),
        btn('Создать тест', () => send('Создай один следующий компактный LightBurn-тест для этой цели. Сначала проверь, нет ли уже ожидающей платы.'), 'btn-small')),
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
        `/ingest?plan=${active.plans[0].id}&material=${active.material_id}${active.profile_id ? `&profile=${active.profile_id}` : ''}` : '/ingest', 'Добавить RAW-фото'),
        link('/experiments', 'Все эксперименты')),
      insightBox, memoryBox);
    return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI-исследователь'),
        h('p', {class: 'sub'}, 'Цель → компактный тест → LightBurn → RAW-фото → вывод')),
        link('/experiments', 'Эксперименты')),
      h('div', {class: 'research-layout'}, list, activePanel, evidencePanel), startPanel);
  }});
})();
