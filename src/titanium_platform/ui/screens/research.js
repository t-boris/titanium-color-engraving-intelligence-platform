/* Research session: a compact conversation beside the actual laser, stock and LightBurn artifacts. */
'use strict';
(() => {
  const {h, btn, field, link, get, post, del, toast, fail, pill, confirmBox} = App;
  const goalName = (goals, id) => goals.find((item) => item.id === id)?.name || id;
  const option = (value, label) => h('option', {value}, label);
  const SETTING_NAMES = {power: 'Power, %', frequency: 'Frequency, kHz', speed: 'Speed, mm/s', pulse_width: 'Pulse width, ns',
    line_interval: 'Line interval, mm', passes: 'Passes', global_passes: 'Global passes', max_width_mm: 'Width limit, mm',
    max_height_mm: 'Height limit, mm', matrix: 'Matrix', x_axis: 'X axis', y_axis: 'Y axis', x_min: 'X min', x_max: 'X max', x_count: 'X count',
    y_min: 'Y min', y_max: 'Y max', y_count: 'Y count', geometry: 'Sample', registration: 'Markers', patch_size_mm: 'Sample size, mm',
    patches: 'Samples', recipes: 'Recipes', widths_mm: 'Widths, mm', task: 'Task'};
  function proposalSettings(settings) {
    const hidden = new Set(['research_session_id', 'research_goal', 'source_pair_id']);
    const show = (value) => value == null ? 'not specified' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    return h('dl', {class: 'facts'}, ...Object.entries(settings || {}).filter(([key]) => !hidden.has(key)).map(([key, value]) =>
      [h('dt', {}, SETTING_NAMES[key] || key), h('dd', {}, show(value))]));
  }

  /** Download LightBurn: one press at a time, a failure stays beside the button with a retry (Lifecycle.downloadButton); a plain link where that is not loaded. */
  function downloadLightBurn(plan) {
    const path = `/plans/${plan.id}/export.lbrn2`;
    if (typeof Lifecycle === 'undefined') return h('a', {href: '/api' + path, class: 'btn btn-small'}, 'Download LightBurn');
    return Lifecycle.downloadButton(path, `${String(plan.name || 'plate').replace(/[^\w.-]+/g, '_')}.lbrn2`, 'Download LightBurn', {cls: 'btn-small'}).el;
  }

  function artifacts(plans) {
    return plans.length ? plans.map((plan) => h('div', {class: 'research-artifact'},
      h('div', {}, link('/plans/' + plan.id, plan.name), pill(({Exported: 'Exported',
        Superseded: 'Replaced', Cancelled: 'Cancelled'})[plan.status] || 'Ready')),
      ['Superseded', 'Cancelled'].includes(plan.status) ? null : downloadLightBurn(plan))) :
      [h('p', {class: 'muted small'}, 'No plate yet. Describe the criterion and ask the AI to suggest a test.')];
  }

  function photoItems(photos) {
    return photos.length ? photos.map((photo) => h('div', {class: 'research-artifact'},
      h('div', {}, link(photo.status === 'Accepted' ? '/analysis/' + photo.id : '/ingest?pair=' + photo.id,
        `Photo #${photo.id} · ${photo.photo_name}`),
      pill(photo.status === 'Accepted' ? 'Accepted' : 'Review', photo.status === 'Accepted' ? 'ok' : 'warn')))) :
      [h('p', {class: 'muted small'}, 'No photos for this plate yet.')];
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
        action.disabled = true; feedback.textContent = 'Creating test…';
        try {
          const made = await createProposal(message.id, index, p.pending_plan_id || null);
          feedback.replaceChildren(h('a', {href: made.plan_url}, `Open created plate #${made.plan_id}`));
          action.hidden = true;
        } catch (e) { feedback.textContent = e.message; action.disabled = false; }
      };
      const action = btn(p.pending_plan_id ? `Replace plate #${p.pending_plan_id}…` : 'Create test', () => {
        if (!p.pending_plan_id) return create();
        return confirmBox('Replace pending plate', `Plate #${p.pending_plan_id} will remain in the history as replaced; its file will no longer be available for download. Create the proposed test?`,
          'Replace and create', create);
      }, 'primary btn-small', !!p.pending_plan_id && !p.pending_replaceable);
      if (item.created_plan) { action.hidden = true; feedback.append(link(`/plans/${item.created_plan.plan_id}`, `Open created plate #${item.created_plan.plan_id}`)); }
      return h('div', {class: 'card stack research-proposal'}, h('strong', {}, `Proposal: ${p.name}`),
        h('p', {class: 'small'}, p.description || '', size ? ` · size ${size.width} × ${size.height} mm` : ' · size not specified',
          ` · ${p.time_unavailable_reason || 'time estimate unavailable'}`),
        p.pending_plan_id && !p.pending_replaceable ? h('p', {class: 'alert warn'}, `Plate #${p.pending_plan_id} already has a photo: review it first.`) : null,
        h('details', {}, h('summary', {}, 'Proposed test settings'), proposalSettings(p.test_settings),
          h('h4', {}, 'Cleanup'), proposalSettings(p.cleanup_settings),
          p.label_settings ? [h('h4', {}, 'Markers'), proposalSettings(p.label_settings)] : null),
        action, feedback);
    });
    return h('article', {class: `research-message ${message.role === 'user' ? 'from-user' : 'from-ai'}`},
      h('small', {}, message.role === 'user' ? 'You' : 'AI researcher'),
      message.role === 'user' ? (message.content.length > 260 ?
        h('details', {class: 'research-long-message'},
          h('summary', {}, message.content.slice(0, 170).trimEnd() + '…'),
          h('p', {class: 'research-user-text'}, message.content)) :
        h('p', {class: 'research-user-text'}, message.content)) : App.renderMarkdown(message.content),
      created.length || pairs.length ? h('div', {class: 'research-message-links'},
        ...created.map((item) => h('a', {href: item.result.download_url, class: 'btn btn-small'},
          `Download plate #${item.result.plan_id}`)),
        ...pairs.map((pairId) => link('/analysis/' + pairId, `Review #${pairId}`))) : null, previews);
  }

  App.register({id: 'research', async render(ctx) {
    const [devices, stocks, goals, sessions] = await Promise.all([
      get('/devices'), get('/materials?limit=1'), get('/application-goals'), get('/research/sessions')]);
    const hasMaterials = (Array.isArray(stocks) ? stocks.length : stocks.all) > 0;     // the records themselves are chosen in the picker, a page at a time
    const requested = Number(ctx.arg);
    const selected = sessions.find((item) => item.id === requested) || sessions[0];
    const active = selected ? await get('/research/sessions/' + selected.id) : null;
    const list = h('section', {class: 'card research-sidebar'},
      h('div', {class: 'research-panel-head'}, h('h3', {}, 'Research sessions'), pill(sessions.length)),
      h('div', {class: 'research-session-list'},
        ...sessions.map((item) => h('a', {href: '#/research/' + item.id,
          class: `research-session-link ${item.id === active?.id ? 'active' : ''}`},
          h('strong', {}, goalName(goals, item.goal)),
          h('span', {}, item.target),
          h('small', {}, `${item.device_name} · ${item.lens_name} · ${item.material_name}`)))),
      active ? btn('Delete research session', () => confirmBox('Delete research session',
        'This research session will disappear from the list. Plates, photos and measurements will remain in Experiments; the conversation history will remain in the local database.',
        'Delete research session', async () => {
          await del(`/research/sessions/${active.id}`);
          toast('Research session removed from the list', 'ok');
          if (location.hash === '#/research') App.render();
          else App.go('/research');
        }), 'btn-small danger research-delete') : null);

    const form = Forms.create();
    const deviceSelect = h('select', {required: true}, devices.map((item) => option(item.id, [item.name, item.lens?.name].filter(Boolean).join(' · '))));
    const materialSelect = MaterialPicker.create({initial: 'recent', name: 'Material and stock'});
    const goalSelect = h('select', {required: true}, goals.map((item) => option(item.id, item.name)));
    const targetInput = h('textarea', {rows: '2', placeholder: 'For example: legible 1 mm black text on Grade 2 with minimum processing time'});
    const deviceField = form.add('device', 'Laser and lens', deviceSelect, {required: true, help: 'the laser must have a lens'});
    const materialField = form.add('material', 'Material and stock', materialSelect, {required: true,
      read: () => (materialSelect.value ? {ok: true, value: Number(materialSelect.value)} : {ok: false, message: 'Select stock: a specific batch or sheet'})});
    const goalField = form.add('goal', 'Task', goalSelect, {required: true});
    // research.create_session: the target is 4 to 600 characters; a longer text is refused with its length, not cut short
    const targetField = form.add('target', 'Success criterion', targetInput, {required: true, minLength: 4, maxLength: 600});
    const createButton = btn('Start research', async () => {
      const v = form.collect();
      if (!v) return;
      createButton.disabled = true;
      try {
        const session = await post('/research/sessions', {device_id: Number(v.device), material_id: v.material, goal: v.goal, target: v.target});
        toast('Research session created', 'ok');
        App.go('/research/' + session.id);
      } catch (error) { form.fail(error); createButton.disabled = false; }
    }, 'primary', !devices.length || !hasMaterials);
    const startPanel = h('details', {class: 'card research-new', open: !active},
      h('summary', {}, 'New research session'),
      h('div', {class: 'research-start-grid'}, deviceField, materialField, goalField),
      targetField, form.error,
      h('div', {class: 'row'}, createButton));
    if (!active) return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI researcher'),
        h('p', {class: 'sub'}, 'Goal → compact test → LightBurn → RAW photo → conclusion'))),
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
      h('summary', {}, 'Saved findings'), insightContent);
    const memoryContent = h('div', {}, active.memory ? App.renderMarkdown(active.memory.summary) : null);
    const memoryBox = h('details', {class: 'research-memory', hidden: !active.memory},
      h('summary', {}, 'Research memory'), memoryContent);
    const scopeCount = h('span', {}, `${active.insights.length} findings · ${active.plans.length} plates · ${(active.photos || []).length} photos`);
    const chatBody = h('div', {class: 'research-chat-body', role: 'log', 'aria-live': 'polite'},
      ...active.messages.map((message) => messageNode(message, createProposal)));
    if (active.has_older_messages && active.messages.length) {
      let oldest = active.messages[0].id;
      const olderButton = btn('Show previous messages', async () => {
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
      'Ask what is known or request a proposed test. Plate creation is confirmed separately below the proposal.'));
    const input = h('textarea', {rows: '2', maxlength: '4000', 'aria-label': 'Message to AI researcher (up to 4,000 characters)',
      placeholder: 'For example: which lines are already visible? Suggest the next compact test and explain what it will reveal.'});
    let busy = false;
    const send = async (suggested, advisory = false) => {
      if (busy) return;
      const value = String(suggested || input.value).trim();
      if (!value) return;
      busy = true; sendButton.disabled = true; sendButton.textContent = 'Analyzing…';
      chatBody.append(messageNode({role: 'user', content: value}),
        h('p', {class: 'research-thinking muted small'}, 'AI is reviewing the data and may use tools…'));
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
        scopeCount.textContent = `${result.session.insights.length} findings · ${result.session.plans.length} plates · ${(result.session.photos || []).length} photos`;
        chatBody.scrollTop = chatBody.scrollHeight;
      } catch (error) {
        chatBody.querySelector('.research-thinking')?.remove();
        chatBody.append(h('p', {class: 'alert bad', role: 'alert'}, error.message));
        input.value = value;
        fail(error);
      } finally { busy = false; sendButton.disabled = false; sendButton.textContent = 'Send'; }
    };
    const sendButton = btn('Send', () => send(), 'primary');
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); send(); }
    });
    const targetPreview = active.target.length > 105 ? active.target.slice(0, 102).trimEnd() + '…' : active.target;
    const activePanel = h('section', {class: 'card research-main'},
      h('div', {class: 'research-panel-head'}, h('div', {class: 'research-heading'}, h('h3', {}, goalName(goals, active.goal)),
        h('details', {class: 'research-target'}, h('summary', {title: active.target}, targetPreview),
          h('p', {}, active.target))), pill(active.model, 'ok')),
      h('div', {class: 'research-quick'},
        btn('What is already known?', () => send('What is already known about this goal? Include accepted photo IDs and the limits of the conclusions.', true), 'btn-small'),
        btn('Explain the result', () => send('Analyze the latest accepted photo review: what was learned about the settings and what are the limitations? Cite sources.', true), 'btn-small'),
        btn('Suggest a test', () => send('Suggest the most useful compact next test. State the hypothesis, success criterion and area; validate it using preview_test.', true), 'btn-small')),
      chatBody,
      h('div', {class: 'research-compose'}, input, sendButton, h('small', {class: 'muted'}, '⌘/Ctrl + Enter')));
    const evidencePanel = h('aside', {class: 'card research-evidence'},
      h('h3', {}, 'Laser and results'),
      h('div', {class: 'research-scope'},
        h('strong', {}, `${selected.device_name} · ${selected.lens_name}`),
        h('span', {}, [selected.material_name, selected.material_grade].filter(Boolean).join(' · ')),
        scopeCount),
      h('h4', {}, 'Plates and files'), planBox,
      h('h4', {}, 'Photos and reviews'), photoBox,
      h('div', {class: 'research-evidence-actions'}, link(active.plans.length ?
        `/ingest?plan=${active.plans[0].id}&material=${active.material_id}&device=${active.device_id}&lens=${App.lensParam(active.lens_id)}` : '/ingest', 'Add RAW photo'),
        link('/experiments', 'All experiments')),
      insightBox, memoryBox);
    return h('div', {class: 'research-page'},
      h('div', {class: 'dashboard-hero'}, h('div', {}, h('h2', {}, 'AI researcher'),
        h('p', {class: 'sub'}, 'Goal → compact test → LightBurn → RAW photo → conclusion')),
        link('/experiments', 'Experiments')),
      h('div', {class: 'research-layout'}, list, activePanel, evidencePanel), startPanel);
  }});
})();
