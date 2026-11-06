/* Local network pairing, certificate, outbound services, and workshop OpenAI key settings. */
'use strict';
(() => {
  const {h, btn, field, pill, get, post, put, del, toast, fail, modal, confirmBox, table} = App;
  const when = (iso) => (iso ? new Date(iso).toLocaleString('en-US', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const EMPTY_CODE = '— — — — — —';
  let countdown = null;
  const stopCountdown = () => { if (countdown) { clearInterval(countdown); countdown = null; } };

  // ---- the local network -------------------------------------------------------------------------------------------------------------

  function lanCard(st, reload) {
    const enabled = h('input', {type: 'checkbox', class: 'lan-enabled', 'aria-label': 'Tablet access over the local network'});
    enabled.checked = !!st.enabled;
    const f = Forms.create();
    const port = Forms.numberInput(Forms.QUANTITIES.lanPort, {value: st.port});
    const name = h('input', {maxlength: 64, value: st.name || ''});
    const portField = f.add('port', 'Port', port, {quantity: 'lanPort', required: true});
    const nameField = f.add('name', 'Workshop name on tablet', name, {empty: ''});
    const apply = btn('Apply', async () => {
      const v = f.collect();
      if (!v) return;
      try {
        await put('/lan', {enabled: enabled.checked, port: v.port, name: v.name});
        toast(enabled.checked ? 'Local network access enabled' : 'Local network access disabled', 'ok');
        reload();
      } catch (e) { f.fail(e); }
    }, 'primary');
    const state = st.running ? pill('running', 'ok') : st.enabled ? pill('not running', 'bad') : pill('off');
    const urls = st.urls.length ? h('ul', {class: 'lan-urls'}, st.urls.map((u) => h('li', {}, h('code', {}, u))))
      : h('p', {class: 'muted small'}, 'This computer is not connected to a network; no addresses are available.');
    return h('div', {class: 'card stack'}, h('h3', {}, 'Local network ', state),
      h('p', {class: 'small muted'}, 'A tablet on the same network can open the workshop at the address below. This is a separate encrypted server; '
        + 'the app address on this computer stays the same, and the workshop is not exposed to the internet.'),
      h('label', {class: 'row'}, enabled, h('span', {}, 'Tablet access over the local network')),
      h('div', {class: 'toolbar'}, portField, nameField, apply), f.error,
      st.error ? h('p', {class: 'alert bad', role: 'alert'}, 'Server did not start: ', st.error) : null,
      h('div', {}, h('p', {class: 'small'}, st.running ? 'Tablet addresses:' : 'Addresses for the tablet after access is enabled:'), urls));
  }

  function certificateCard(st) {
    return h('div', {class: 'card stack'}, h('h3', {}, 'Workshop certificate'),
      h('p', {class: 'small muted'}, 'The tablet connection is encrypted using a certificate issued by this workshop’s certificate authority. Install the authority certificate '
        + 'once on the tablet, or compare its fingerprint when the browser warns before continuing.'),
      h('p', {}, 'Certificate authority SHA-256 fingerprint:'), h('code', {class: 'fingerprint'}, st.fingerprint || '—'),
      h('div', {class: 'row'}, h('a', {class: 'btn', href: '/api/lan/ca', download: 'titanium-workshop-ca.crt'}, 'Download certificate'),
        h('span', {class: 'small muted'}, `server certificate valid until ${when(st.certificate_until)} and renewed automatically`)),
      h('details', {}, h('summary', {}, 'How to install on a tablet'),
        h('p', {class: 'small'}, 'iPad: open the workshop /pair page on the tablet and select “download the certificate”, then Settings → Profile Downloaded → '
          + 'Install. Then go to Settings → General → About → Certificate Trust Settings and trust the workshop certificate.'),
        h('p', {class: 'small'}, 'Android: download the certificate the same way, then go to Settings → Security → Encryption & credentials → Install a certificate → '
          + 'CA certificate.')));
  }

  function codeCard(st, reload) {
    const code = st.code || null;
    const digits = h('div', {class: 'lan-code', 'aria-live': 'polite'}, code ? code.code : EMPTY_CODE);
    const left = h('p', {class: 'small muted'}, code ? `expires in ${mmss(code.expires_in_s)}` : 'No code is active. A new code is valid for five minutes and one use.');
    stopCountdown();
    if (code) {
      let seconds = code.expires_in_s;
      countdown = setInterval(() => {
        seconds -= 1;
        if (seconds <= 0) { stopCountdown(); digits.textContent = EMPTY_CODE; left.textContent = 'Code expired. Request a new one.'; return; }
        left.textContent = `expires in ${mmss(seconds)}`;
      }, 1000);
    }
    const ask = btn(code ? 'Another code' : 'New code', async () => { try { await post('/lan/code', {}); reload(); } catch (e) { fail(e); } }, 'primary');
    const first = st.urls[0];
    return h('div', {class: 'card stack'}, h('h3', {}, 'Tablet code'),
      h('p', {class: 'small muted'}, 'On the tablet, open ', first ? h('code', {}, first + '/pair') : 'the workshop /pair page',
        ' and enter the code. The code is displayed only on this computer.'),
      digits, left, h('div', {class: 'row'}, ask, st.running ? null : h('span', {class: 'small muted'}, 'Tablet server is off: enable access above.')));
  }

  function devicesCard(st, reload) {
    const rename = (d) => {
      const input = h('input', {maxlength: 64, 'aria-label': 'Tablet name'});
      input.value = d.name;
      modal('Rename tablet', field('Name', input), [{label: 'Cancel', run: (m) => m.close()},
        {label: 'Save', cls: 'primary', run: async (m) => { await put(`/lan/devices/${d.id}`, {name: input.value}); m.close(); toast('Name saved', 'ok'); reload(); }}]);
    };
    const revoke = (d) => confirmBox('Revoke tablet access', `Tablet “${d.name}” will no longer open the workshop; its next request will be denied. `
      + 'It can be connected again with a new code.', 'Revoke', async () => { await post(`/lan/devices/${d.id}/revoke`, {}); toast('Access revoked', 'ok'); reload(); });
    const rows = (st.devices || []).map((d) => [h('span', {class: 'device-name'}, d.name), when(d.created_at), when(d.last_seen_at),
      d.revoked_at ? pill(`revoked ${when(d.revoked_at)}`, 'bad') : pill('connected', 'ok'),
      d.revoked_at ? null : h('div', {class: 'row'}, btn('Rename', () => rename(d), 'btn-small'), btn('Revoke', () => revoke(d), 'danger btn-small'))]);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Connected tablets'),
      table(['Tablet', 'Connected', 'Last visit', 'Status', ''], rows, 'No tablets are connected yet.', true));
  }

  // ---- what may be reached outside this computer ---------------------------------------------------------------------------------------

  const SWITCHES = [
    ['ai', 'AI researcher and planner explanations', 'contact OpenAI only with a key and when you invoke them'],
    ['google_fonts', 'Google Fonts', 'font families and files are downloaded only on request'],
    ['update_checks', 'Desktop update checks', 'checks GitHub Releases for a new version without downloading or installing it; '
      + 'also permits automatic checks for new laboratory releases in the cloud'],
    ['cloud', 'Laboratory cloud', 'catalog, release publishing, invitations, and sign-in; contacts the cloud only when you sign in, publish, or check for updates']];

  /** The address of the cloud (cloud.api_url): the production service unless the operator names another, for example one under test. */
  function cloudAddress(cloud) {
    if (!cloud) return null;
    const f = Forms.create();
    const input = h('input', {placeholder: cloud.default, value: cloud.custom ? cloud.api_url : ''});
    const addressField = f.add('url', 'Laboratory cloud address', input, {empty: '', help: `leave blank for the default ${cloud.default}; use HTTPS, or HTTP only for 127.0.0.1`});
    const save = btn('Save', async () => {
      const v = f.collect();
      if (!v) return;
      try {
        const saved = await put('/cloud/settings', {api_url: v.url});
        input.value = saved.custom ? saved.api_url : '';
        toast(saved.custom ? 'Cloud address saved' : 'Cloud address reset to default', 'ok');
      } catch (e) { f.fail(e); }       // the server's words stay under the box, with what was typed left as it was
    }, 'btn-small');
    return h('div', {class: 'stack cloud-address'}, h('div', {class: 'toolbar'}, addressField, save), f.error);
  }

  const KEY_SOURCE = {environment: 'from the OPENAI_API_KEY environment variable', workshop: 'saved in the workshop',
    developer_file: 'from the developer .env.local file'};

  /** The OpenAI key of the AI features (BUG-007): kept by the workshop (ai/openai.key, readable only by this user), never shown back. */
  function aiKey(key, reload) {
    if (!key) return null;
    const f = Forms.create();
    const input = h('input', {type: 'password', autocomplete: 'off', placeholder: 'sk-…'});
    const state = key.set ? pill(`key set (…${key.ending}), ${KEY_SOURCE[key.source] || ''}`, 'ok') : pill('key not set', 'bad');
    // the key is sent as typed: what a key may look like is the server's rule (research.save_key) and its words are shown under the box
    const keyField = f.add('key', 'New key', input, {read: () => ({ok: true, value: input.value}),
      help: 'stored only in the workshop folder (ai/openai.key, accessible only to your user); '
        + 'excluded from backups, diagnostics, and laboratory releases; OPENAI_API_KEY takes precedence when set'});
    const save = btn('Save key', async () => {
      const v = f.collect();
      if (!v) return;
      try { await put('/network/ai-key', {key: v.key}); input.value = ''; toast('OpenAI key saved in the workshop', 'ok'); reload(); }
      catch (e) { f.fail(e); }
    }, 'btn-small');
    const remove = key.workshop_file ? btn('Delete key', () => confirmBox('Delete OpenAI key',
      'The key will be removed from the workshop; the AI researcher and explanations will stop working until a key is entered again.', 'Delete',
      async () => { await del('/network/ai-key'); toast('Key deleted', 'ok'); reload(); }), 'danger btn-small') : null;
    return h('div', {class: 'stack ai-key'}, h('div', {class: 'row'}, h('strong', {}, 'OpenAI key'), state),
      h('div', {class: 'toolbar'}, keyField, save, remove), f.error);
  }

  function outboundCard(net, cloud, key, reload) {
    const row = ([key, label, help]) => {
      const box = h('input', {type: 'checkbox', class: 'switch', 'aria-label': label});
      box.checked = !!net[key];
      box.addEventListener('change', async () => {
        try { await put('/network', {[key]: box.checked}); toast(box.checked ? `Enabled: ${label}` : `Disabled: ${label}`, 'ok'); }
        catch (e) { box.checked = !box.checked; fail(e); }
      });
      return h('label', {class: 'row'}, box, h('span', {}, label, h('span', {class: 'small muted'}, ' — ', help)));
    };
    return h('div', {class: 'card stack'}, h('h3', {}, 'External services'),
      h('p', {class: 'small muted'}, 'Services the app can contact outside this computer. The app sends no telemetry.'),
      SWITCHES.map(row), aiKey(key, reload), cloudAddress(cloud));
  }

  App.register({id: 'network', async render() {
    stopCountdown();
    const [st, net, cloud, key] = await Promise.all([get('/lan'), get('/network'), get('/cloud/settings').catch(() => null),
      get('/network/ai-key').catch(() => null)]);
    const reload = () => App.render({preserveScroll: true});
    return h('div', {class: 'stack'},
      h('div', {}, h('h2', {}, 'Network'), h('p', {class: 'sub'}, 'Tablet access over the local network and services the app can contact outside it.')),
      lanCard(st, reload), codeCard(st, reload), certificateCard(st), devicesCard(st, reload), outboundCard(net, cloud, key, reload));
  }});
})();
