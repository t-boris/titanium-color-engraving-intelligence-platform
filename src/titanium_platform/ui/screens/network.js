/* Сеть (feature electron, REQ-082, DEC-047; REQ-080). Доступ с планшета по локальной сети: отдельный сервер с шифрованием и собственным центром
   сертификации мастерской (отпечаток и сертификат для установки на планшете), код сопряжения на пять минут с обратным отсчётом, список
   подключённых планшетов с отзывом. И переключатели того, куда приложение вообще может обращаться: AI-исследователь, Google Fonts, проверка
   обновлений, облако лабораторий (и его адрес, REQ-086) — больше никуда ничего не отправляется. Имена планшетов показываются только текстом (узлы h()). Адрес: #/network */
'use strict';
(() => {
  const {h, btn, field, pill, get, post, put, toast, fail, modal, confirmBox, table} = App;
  const when = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const EMPTY_CODE = '— — — — — —';
  let countdown = null;
  const stopCountdown = () => { if (countdown) { clearInterval(countdown); countdown = null; } };

  // ---- the local network -------------------------------------------------------------------------------------------------------------

  function lanCard(st, reload) {
    const enabled = h('input', {type: 'checkbox', class: 'lan-enabled', 'aria-label': 'Доступ с планшета по локальной сети'});
    enabled.checked = !!st.enabled;
    const port = h('input', {type: 'number', min: 1024, max: 65535, step: 1, 'aria-label': 'Порт'});
    port.value = st.port;
    const name = h('input', {maxlength: 64, 'aria-label': 'Имя мастерской на планшете'});
    name.value = st.name || '';
    const apply = btn('Применить', async () => {
      try {
        await put('/lan', {enabled: enabled.checked, port: Number(port.value), name: name.value});
        toast(enabled.checked ? 'Доступ по локальной сети включён' : 'Доступ по локальной сети выключен', 'ok');
        reload();
      } catch (e) { fail(e); }
    }, 'primary');
    const state = st.running ? pill('работает', 'ok') : st.enabled ? pill('не запущен', 'bad') : pill('выключен');
    const urls = st.urls.length ? h('ul', {class: 'lan-urls'}, st.urls.map((u) => h('li', {}, h('code', {}, u))))
      : h('p', {class: 'muted small'}, 'Компьютер сейчас не подключён к сети: адресов нет.');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Локальная сеть ', state),
      h('p', {class: 'small muted'}, 'Планшет в той же сети открывает мастерскую по адресу ниже. Это отдельный сервер с шифрованием; '
        + 'обычный адрес приложения на этом компьютере не меняется, и из интернета мастерская не видна.'),
      h('label', {class: 'row'}, enabled, h('span', {}, 'Доступ с планшета по локальной сети')),
      h('div', {class: 'toolbar'}, field('Порт', port), field('Имя мастерской на планшете', name), apply),
      st.error ? h('p', {class: 'alert bad', role: 'alert'}, 'Сервер не запустился: ', st.error) : null,
      h('div', {}, h('p', {class: 'small'}, st.running ? 'Адреса для планшета:' : 'Адреса, по которым планшет откроет мастерскую после включения:'), urls));
  }

  function certificateCard(st) {
    return h('div', {class: 'card stack'}, h('h3', {}, 'Сертификат мастерской'),
      h('p', {class: 'small muted'}, 'Соединение планшета шифруется сертификатом, который выписал центр сертификации этой мастерской. Планшет либо устанавливает '
        + 'сертификат центра один раз, либо при предупреждении браузера сверяет его отпечаток и продолжает.'),
      h('p', {}, 'Отпечаток SHA-256 центра сертификации:'), h('code', {class: 'fingerprint'}, st.fingerprint || '—'),
      h('div', {class: 'row'}, h('a', {class: 'btn', href: '/api/lan/ca', download: 'titanium-workshop-ca.crt'}, 'Скачать сертификат'),
        h('span', {class: 'small muted'}, `серверный сертификат действует до ${when(st.certificate_until)} и обновляется сам`)),
      h('details', {}, h('summary', {}, 'Как установить на планшете'),
        h('p', {class: 'small'}, 'iPad: откройте на планшете адрес мастерской со страницей /pair, нажмите «скачайте сертификат», затем Настройки → «Профиль загружен» → '
          + 'Установить; после этого Настройки → Основные → Об этом устройстве → Доверие сертификатам → включите доверие сертификату мастерской.'),
        h('p', {class: 'small'}, 'Android: скачайте сертификат тем же способом, затем Настройки → Безопасность → Шифрование и учётные данные → Установить сертификат → '
          + 'Сертификат ЦС.')));
  }

  function codeCard(st, reload) {
    const code = st.code || null;
    const digits = h('div', {class: 'lan-code', 'aria-live': 'polite'}, code ? code.code : EMPTY_CODE);
    const left = h('p', {class: 'small muted'}, code ? `действует ещё ${mmss(code.expires_in_s)}` : 'Кода сейчас нет. Новый код действует пять минут и один раз.');
    stopCountdown();
    if (code) {
      let seconds = code.expires_in_s;
      countdown = setInterval(() => {
        seconds -= 1;
        if (seconds <= 0) { stopCountdown(); digits.textContent = EMPTY_CODE; left.textContent = 'Код истёк. Попросите новый.'; return; }
        left.textContent = `действует ещё ${mmss(seconds)}`;
      }, 1000);
    }
    const ask = btn(code ? 'Другой код' : 'Новый код', async () => { try { await post('/lan/code', {}); reload(); } catch (e) { fail(e); } }, 'primary');
    const first = st.urls[0];
    return h('div', {class: 'card stack'}, h('h3', {}, 'Код для планшета'),
      h('p', {class: 'small muted'}, 'На планшете откройте ', first ? h('code', {}, first + '/pair') : 'адрес мастерской со страницей /pair',
        ' и введите код. Код показывается только на этом компьютере и никогда не передаётся по сети.'),
      digits, left, h('div', {class: 'row'}, ask, st.running ? null : h('span', {class: 'small muted'}, 'Сервер для планшетов выключен: включите доступ выше.')));
  }

  function devicesCard(st, reload) {
    const rename = (d) => {
      const input = h('input', {maxlength: 64, 'aria-label': 'Имя планшета'});
      input.value = d.name;
      modal('Переименовать планшет', field('Имя', input), [{label: 'Отмена', run: (m) => m.close()},
        {label: 'Сохранить', cls: 'primary', run: async (m) => { await put(`/lan/devices/${d.id}`, {name: input.value}); m.close(); toast('Имя сохранено', 'ok'); reload(); }}]);
    };
    const revoke = (d) => confirmBox('Отозвать доступ планшета', `Планшет «${d.name}» больше не откроет мастерскую: при следующем запросе ему будет отказано. `
      + 'Подключить его снова можно новым кодом.', 'Отозвать', async () => { await post(`/lan/devices/${d.id}/revoke`, {}); toast('Доступ отозван', 'ok'); reload(); });
    const rows = (st.devices || []).map((d) => [h('span', {class: 'device-name'}, d.name), when(d.created_at), when(d.last_seen_at),
      d.revoked_at ? pill(`отозван ${when(d.revoked_at)}`, 'bad') : pill('подключён', 'ok'),
      d.revoked_at ? null : h('div', {class: 'row'}, btn('Переименовать', () => rename(d), 'btn-small'), btn('Отозвать', () => revoke(d), 'danger btn-small'))]);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Подключённые планшеты'),
      table(['Планшет', 'Подключён', 'Последний визит', 'Состояние', ''], rows, 'Пока ни один планшет не подключён.', true));
  }

  // ---- what may be reached outside this computer ---------------------------------------------------------------------------------------

  const SWITCHES = [
    ['ai', 'AI-исследователь и пояснения планировщика', 'обращаются к OpenAI только с ключом и только когда вы их вызываете'],
    ['google_fonts', 'Шрифты Google Fonts', 'список семейств и файлы шрифтов загружаются только когда вы их запрашиваете'],
    ['update_checks', 'Проверка обновлений в настольном приложении', 'спрашивает у GitHub Releases, вышла ли новая версия; ничего не скачивает и не ставит; '
      + 'разрешает и автоматическую проверку новых выпусков лабораторий из облака'],
    ['cloud', 'Облако лабораторий', 'каталог, публикация выпусков, приглашения и вход; обращается к облаку только когда вы входите, публикуете или проверяете обновления']];

  /** The address of the cloud (cloud.api_url): the production service unless the operator names another, for example one under test. */
  function cloudAddress(cloud) {
    if (!cloud) return null;
    const input = h('input', {placeholder: cloud.default, 'aria-label': 'Адрес облака лабораторий'});
    input.value = cloud.custom ? cloud.api_url : '';
    const save = btn('Сохранить', async () => {
      try {
        const saved = await put('/cloud/settings', {api_url: input.value.trim()});
        input.value = saved.custom ? saved.api_url : '';
        toast(saved.custom ? 'Адрес облака сохранён' : 'Адрес облака: стандартный', 'ok');
      } catch (e) { fail(e); }
    }, 'btn-small');
    return h('div', {class: 'toolbar cloud-address'}, field('Адрес облака лабораторий', input, `пусто — стандартный адрес ${cloud.default}; https, или http только для 127.0.0.1`), save);
  }

  function outboundCard(net, cloud) {
    const row = ([key, label, help]) => {
      const box = h('input', {type: 'checkbox', class: 'switch', 'aria-label': label});
      box.checked = !!net[key];
      box.addEventListener('change', async () => {
        try { await put('/network', {[key]: box.checked}); toast(box.checked ? `Включено: ${label}` : `Выключено: ${label}`, 'ok'); }
        catch (e) { box.checked = !box.checked; fail(e); }
      });
      return h('label', {class: 'row'}, box, h('span', {}, label, h('span', {class: 'small muted'}, ' — ', help)));
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'Внешние службы'),
      h('p', {class: 'small muted'}, 'Всё, к чему приложение может обращаться за пределами этого компьютера. Больше никуда оно ничего не отправляет: телеметрии нет.'),
      SWITCHES.map(row), cloudAddress(cloud));
  }

  App.register({id: 'network', async render() {
    stopCountdown();
    const [st, net, cloud] = await Promise.all([get('/lan'), get('/network'), get('/cloud/settings').catch(() => null)]);
    const reload = () => App.render({preserveScroll: true});
    return h('div', {class: 'stack'},
      h('div', {}, h('h2', {}, 'Сеть'), h('p', {class: 'sub'}, 'Планшет в мастерской по локальной сети и то немногое, к чему приложение обращается за её пределами.')),
      lanCard(st, reload), codeCard(st, reload), certificateCard(st), devicesCard(st, reload), outboundCard(net, cloud));
  }});
})();
