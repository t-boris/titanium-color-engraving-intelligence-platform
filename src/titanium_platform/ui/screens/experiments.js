/* Компактный обзор: платы, гравировки и сохранённые выводы видны одновременно. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, patch, del, toast, confirmBox, modal} = App;
  const KIND = {'Awaiting check': ['Ожидает проверки', ''], 'Needs correction': ['Требует исправления', 'warn'],
    'Ready to accept': ['Готова к принятию', 'ok'], Accepted: ['Принята', 'ok']};
  const MODE = {'Calibration plate': 'Калибровочная матрица', 'Laser capability test': 'Тест возможностей лазера',
    'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла'};
  const PURPOSE = {line: 'Линии', text: 'Текст', color: 'Цвет', image: 'Изображение'};
  const settingSummary = (p) => p ? [
    p.power == null ? null : `${p.power}%`, p.frequency == null ? null : `${p.frequency} кГц`,
    p.speed == null ? null : `${p.speed} мм/с`,
    `Q-Pulse ${p.pulse_width == null ? 'не записан' : p.pulse_width + ' нс'}`,
    p.line_interval == null ? null : `шаг ${p.line_interval} мм`,
    p.passes == null ? null : `${p.passes} проход(а)`,
    p.global_passes == null ? null : `глобально ${p.global_passes}×`,
    p.scan_angle == null ? null : `угол ${p.scan_angle}°`,
    p.angle_increment == null ? null : `приращение ${p.angle_increment}°`,
    p.bidirectional == null ? null : `двунаправленно ${p.bidirectional ? 'да' : 'нет'}`,
    p.cross_hatch == null ? null : `перекрёстная заливка ${p.cross_hatch ? 'да' : 'нет'}`,
    p.source_settings?.wobbleEnable?.Value === '1'
      ? `Wobble: размер ${p.source_settings.wobbleSize?.Value ?? '—'} мм, шаг ${p.source_settings.wobbleStep?.Value ?? '—'} мм` : null,
  ].filter(Boolean).join(' · ') : null;
  const checks = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'проверка' :
    n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'проверки' : 'проверок'}`;
  const stat = (value, label, kind = '') => h('div', {class: `dashboard-stat ${kind}`}, h('strong', {}, value), h('span', {}, label));
  const panel = (title, count, items, empty, action) => h('section', {class: 'card dashboard-panel'},
    h('div', {class: 'dashboard-panel-head'}, h('h3', {}, title), pill(count), action),
    items.length ? h('div', {class: 'dashboard-list'}, ...items) : h('p', {class: 'muted small'}, empty));

  App.register({id: 'experiments', async render() {
    const [profiles, plans, pairs, devices, materials, goals] = await Promise.all([
      get('/profiles'), get('/plans'), get('/pairs'), get('/devices'), get('/materials'), get('/application-goals')]);
    const rememberedDevice = Number(sessionStorage.getItem('experiment-dashboard-device'));
    const selectedDevice = devices.find((device) => device.id === rememberedDevice) || devices[0];
    const rememberedMaterial = Number(sessionStorage.getItem('experiment-dashboard-material'));
    const selectedMaterial = materials.find((material) => material.id === rememberedMaterial) || materials[0];
    const selectedGoal = goals.find((goal) => goal.id === sessionStorage.getItem('experiment-dashboard-goal')) || goals[0];
    let findings = [];
    if (selectedDevice) {
      try { findings = await get(`/devices/${selectedDevice.id}/findings`); } catch (_) { /* Остальной обзор доступен. */ }
    }
    findings = findings.filter((finding) => finding.material_id === selectedMaterial?.id &&
      finding.lens_id === selectedDevice?.lens?.id);
    let guide = null;
    if (selectedDevice && selectedMaterial && selectedGoal) {
      try { guide = await get(`/application-guide?device_id=${selectedDevice.id}&material_id=${selectedMaterial.id}&goal=${selectedGoal.id}`); }
      catch (error) { guide = {status: 'error', message: error.message, next_step: 'Проверьте материал и параметры лазера.'}; }
    }
    const latest = new Map();
    for (const finding of findings) if (!latest.has(finding.purpose)) latest.set(finding.purpose, finding);
    const reload = () => App.render({preserveScroll: true});
    const byProfile = new Map(profiles.map((profile) => [profile.id, profile]));
    const launches = new Map();
    for (const pair of pairs) {
      const key = pair.engraving_id || `pair-${pair.id}`;
      if (!launches.has(key)) launches.set(key, []);
      launches.get(key).push(pair);
    }
    const hero = h('div', {class: 'dashboard-hero'},
      h('div', {}, h('h2', {}, 'Эксперименты'), h('p', {class: 'sub'}, 'Платы, гравировки и выводы по лазеру')),
      h('div', {class: 'dashboard-actions'},
        link('/research', 'AI-исследователь'),
        profiles.length ? link('/colors?profile=' + (profiles.find((profile) => profile.device?.id === selectedDevice?.id &&
          profile.lens?.id === selectedDevice?.lens?.id) || profiles[0]).id, 'Цветовые варианты') : null,
        btn('Создать плату', () => PlateDialog.open(devices, materials, reload), 'primary', !devices.length),
        link('/ingest', 'Добавить фото')));
    if (!devices.length) return h('div', {class: 'stack'}, hero,
      h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер и установите линзу'), link('/devices', 'Лазеры')));

    const planCards = plans.map((p) => {
      const legacy = byProfile.get(p.profile_id);
      const laser = p.experiment?.device?.name || legacy?.device?.name || legacy?.name || 'Лазер не указан';
      const lens = p.experiment?.lens?.name || legacy?.lens?.name;
      const titanium = p.experiment?.material;
      const material = [titanium?.name, titanium?.grade].filter(Boolean).join(' · ');
      const linked = pairs.filter((pair) => pair.plan_id === p.id);
      const remove = btn('Удалить тест', () => confirmBox('Удалить тест', linked.length
        ? `«${p.name}»: удалить плату и ${checks(linked.length)}? Загруженные копии RAW и LightBurn будут удалены. История измерений сохранится, но перестанет влиять на рекомендации.`
        : `«${p.name}»: удалить плату из экспериментов?`, 'Удалить тест', async () => {
          await del(`/plans/${p.id}${linked.length ? '?with_pairs=true' : ''}`);
          toast('Тест удалён из активных экспериментов', 'ok'); reload();
        }), 'btn-small danger');
      return h('article', {class: 'dashboard-item'},
        h('div', {class: 'dashboard-item-top'}, link('/plans/' + p.id, p.name),
          pill(({Exported: 'Экспортирован', Draft: 'Черновик', Superseded: 'Заменён',
            Cancelled: 'Отменён'})[p.status] || 'Готов')),
        h('p', {class: 'dashboard-item-type'}, p.experiment?.test_name || MODE[p.mode] || p.mode),
        h('p', {class: 'dashboard-meta'}, [laser, lens, material].filter(Boolean).join(' · ')),
        h('div', {class: 'dashboard-item-foot'}, h('span', {}, `${p.layers} слоёв${linked.length ? ` · ${checks(linked.length)}` : ''}`),
          h('span', {class: 'spacer'}), remove));
    });

    const removePhoto = (photo, sameRaw) => btn(sameRaw ? 'Удалить проверку' : 'Удалить фото', () => confirmBox(
      sameRaw ? 'Удалить проверку снимка' : 'Удалить фотографию',
      sameRaw ? 'Эта проверка и её измерения исчезнут из активной базы. Другие проверки того же RAW останутся.'
        : 'Фотография и загруженные файлы исчезнут из активной базы. Измерения останутся в истории, но не будут участвовать в рекомендациях.',
      'Удалить', async () => { await del('/pairs/' + photo.id); toast('Проверка удалена', 'ok'); reload(); }), 'btn-small danger');
    const engravingCards = [...launches.values()].map((photos) => {
      const p = photos[0];
      const profile = byProfile.get(p.profile_id);
      const laser = profile?.device?.name || profile?.name || 'Лазер не указан';
      const lens = profile?.lens?.name;
      const titanium = [p.context?.titanium_name, p.context?.titanium_grade].filter(Boolean).join(' · ');
      const title = p.engraving_title || p.lightburn_name.replace(/\.lbrn2?$/i, '');
      const images = new Map();
      for (const photo of photos) {
        const key = photo.photo_sha256 || `pair-${photo.id}`;
        if (!images.has(key)) images.set(key, []);
        images.get(key).push(photo);
      }
      const current = photos.find((photo) => photo.status === 'Accepted') || photos[0];
      const currentRoute = current.status === 'Accepted' ? `/analysis/${current.id}` : `/ingest?pair=${current.id}`;
      const editTitle = btn('Переименовать', () => {
        const input = h('input', {value: title, maxlength: '120', 'aria-label': 'Название гравировки'});
        const dialog = modal('Название гравировки', field('Название одного запуска', input), [
          {label: 'Сохранить', cls: 'primary', run: async ({close}) => {
            await patch('/engravings/' + encodeURIComponent(p.engraving_id), {title: input.value});
            close(); toast('Название гравировки сохранено', 'ok'); await reload();
          }},
        ]);
        input.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') { ev.preventDefault(); dialog.el.querySelector('.modal>.row:last-child .btn')?.click(); }
        });
      }, 'btn-small');
      const groups = [...images.values()].map((versions) => {
        const first = versions[0];
        const reusedName = [...images.values()].some((other) => other !== versions &&
          other.some((item) => item.photo_name === first.photo_name));
        const name = first.photo_name + (reusedName ? ` · ${(first.photo_sha256 || String(first.id)).slice(0, 8)}` : '');
        return h('div', {class: 'dashboard-photo-group'}, h('strong', {}, name),
          ...versions.map((photo) => {
            const [label, kind] = KIND[photo.status] || [photo.status, ''];
            return h('div', {class: 'dashboard-photo-row'},
              link(photo.status === 'Accepted' ? `/analysis/${photo.id}` : `/ingest?pair=${photo.id}`, `Проверка №${photo.id}`),
              pill(label, kind), removePhoto(photo, versions.length > 1));
          }));
      });
      const reviewCount = photos.filter((photo) => photo.status !== 'Accepted').length;
      return h('article', {class: 'dashboard-item'},
        h('div', {class: 'dashboard-item-top'}, link(currentRoute, title),
          reviewCount ? pill(`${reviewCount} к проверке`, 'warn') : pill('Принято', 'ok')),
        h('p', {class: 'dashboard-meta'}, [laser, lens, titanium].filter(Boolean).join(' · ')),
        h('p', {class: 'dashboard-file', title: p.lightburn_name}, `LightBurn · ${p.lightburn_name}`),
        h('div', {class: 'dashboard-item-foot'}, h('span', {}, `${images.size} фото · ${checks(photos.length)}`),
          h('span', {class: 'spacer'}), editTitle, link('/ingest?rephoto=' + current.id, 'Добавить фото')),
        h('details', {class: 'dashboard-details', open: photos.length <= 3}, h('summary', {}, 'Фотографии и проверки'), ...groups));
    });

    const insightCards = [...latest.values()].sort((a, b) =>
      ['line', 'text', 'color', 'image'].indexOf(a.purpose) - ['line', 'text', 'color', 'image'].indexOf(b.purpose)).map((finding) =>
      h('article', {class: 'dashboard-insight'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PURPOSE[finding.purpose] || finding.purpose),
          pill(finding.status === 'candidate' ? 'Кандидат' : 'Нужен тест', finding.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-insight-preview', title: finding.summary}, finding.summary),
        h('details', {class: 'dashboard-details'}, h('summary', {}, 'Полный вывод и следующий шаг'),
          h('p', {}, finding.summary), h('p', {}, finding.next_test),
          settingSummary(finding.parameters || finding.evidence?.parameters)
            ? h('p', {}, 'Измеренный режим: ' + settingSummary(finding.parameters || finding.evidence?.parameters)) : null,
          link(`/analysis/${finding.pair_id}`, `Измерения · проверка №${finding.pair_id}`))));
    const devicePicker = devices.length > 1 ? h('select', {class: 'dashboard-device', 'aria-label': 'Лазер для выводов',
      onChange: (event) => { sessionStorage.setItem('experiment-dashboard-device', event.target.value); reload(); }},
      devices.map((device) => h('option', {value: device.id, selected: device.id === selectedDevice.id}, device.name))) : null;
    const goalPicker = h('select', {'aria-label': 'Цель исследования', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-goal', event.target.value); reload();
    }}, goals.map((goal) => h('option', {value: goal.id, selected: goal.id === selectedGoal.id}, goal.name)));
    const materialPicker = h('select', {'aria-label': 'Материал и заготовка', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-material', event.target.value); reload();
    }}, materials.map((material) => h('option', {value: material.id, selected: material.id === selectedMaterial?.id},
      [material.name, material.grade, material.batch].filter(Boolean).join(' · '))));
    const nextPlate = guide?.plate ? btn('Создать следующий тест', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true; self.textContent = 'Создаём плату…';
      try {
        const made = await App.post('/application-guide/next-plate', {
          device_id: selectedDevice.id, material_id: selectedMaterial.id, goal: selectedGoal.id});
        toast(`Создана плата ${made.name}`, 'ok'); App.go('/plans/' + made.plan_id);
      } catch (error) { self.disabled = false; self.textContent = 'Создать следующий тест'; App.fail(error); }
    }, 'primary') : null;
    const taskPanel = h('section', {class: 'card dashboard-task'},
      h('div', {class: 'dashboard-task-head'}, h('div', {}, h('h3', {}, 'Рабочая задача'),
        h('p', {class: 'muted small'}, 'Один материал и одна цель: тест → RAW-фото → вывод → следующий тест.')),
      guide?.finding ? pill(guide.finding.status === 'candidate' ? 'Кандидат' : 'Нужна проверка',
        guide.finding.status === 'candidate' ? 'ok' : 'warn') : pill('Нет готового режима', 'warn')),
      h('div', {class: 'dashboard-task-selectors'},
        field('Что хотим сделать', goalPicker),
        field('На каком материале', materialPicker),
        devices.length > 1 ? field('Каким лазером', devicePicker) : h('div', {class: 'dashboard-task-fixed'},
          h('small', {}, 'Лазер и линза'), h('strong', {}, [selectedDevice?.name, selectedDevice?.lens?.name].filter(Boolean).join(' · ')))),
      h('div', {class: 'dashboard-task-result'},
        h('div', {}, h('strong', {}, selectedGoal?.objective || 'Выберите цель и материал'),
          h('p', {}, guide?.message || 'Добавьте конкретную заготовку, чтобы получить следующий тест.'),
          guide?.finding ? h('p', {class: 'muted small'}, `Последний вывод: ${guide.finding.summary}`) : null,
          settingSummary(guide?.finding?.parameters || guide?.finding?.evidence?.parameters)
            ? h('p', {class: 'muted small'}, 'Параметры наблюдения: ' + settingSummary(guide.finding.parameters || guide.finding.evidence.parameters)) : null),
        h('div', {class: 'dashboard-task-next'}, h('small', {}, 'Следующий шаг'),
          h('p', {}, guide?.next_step || 'Создайте материал и первую плату.'), nextPlate,
          guide?.pending_plan_id ? link('/plans/' + guide.pending_plan_id, 'Открыть созданную плату') : null)),
      guide?.plate ? h('p', {class: 'dashboard-task-foot'},
        `Плата: ${guide.plate.test_type === 'text_readability' ? 'надписи 3 × 3, три размера' : guide.plate.test_type === 'material_matrix' ? 'матрица 3 × 3' : guide.plate.test_type} · чистка перед тестом · исходная проверка ${guide.plate.source_pair_id ? '№' + guide.plate.source_pair_id : 'ещё не создана'}`) : null);
    return h('div', {class: 'experiment-dashboard'}, hero,
      taskPanel,
      h('div', {class: 'dashboard-stats'}, stat(plans.length, 'плат'), stat(launches.size, 'гравировок'),
        stat([...new Set(pairs.map((pair) => pair.photo_sha256 || `pair-${pair.id}`))].length, 'фото'),
        stat(pairs.filter((pair) => pair.status !== 'Accepted').length, 'ждут проверки', 'attention')),
      h('div', {class: 'dashboard-columns'},
        panel('Экспериментальные платы', plans.length, planCards, 'Плат пока нет.'),
        panel('Гравировки и фото', launches.size, engravingCards, 'Гравировок пока нет.'),
        panel('Выводы для материала', latest.size, insightCards,
          'Принятый тест возможностей добавит сюда выводы по линиям, тексту, цвету и изображению.',
          link(`/devices/${selectedDevice.id}`, selectedDevice.name))));
  }});
})();
