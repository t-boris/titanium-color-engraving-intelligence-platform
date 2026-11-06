/* Work measurement sources: local data or a connected laboratory release. Source changes require a preview and explicit confirmation (REQ-085). */
'use strict';
const LabSource = (() => {
  const {h, fill, btn, pill, get, post, modal, toast, fail, num, labText, swatch, table} = App;
  const short = (sha) => String(sha || '').slice(0, 12);
  const day = (iso) => String(iso || '').slice(0, 10);
  const when = (iso) => String(iso || '').replace('T', ' ').slice(0, 16);
  const laserName = (l) => (l ? l.public_name || [l.manufacturer, l.model].filter(Boolean).join(' ') || 'laser' : 'laser not specified');
  const lensName = (l) => (l ? (l.focal_length_mm == null ? 'lens' : `lens ${+l.focal_length_mm} mm`) : 'lens unknown');
  const materialName = (m) => (m ? [m.family, m.grade, m.thickness_mm == null ? null : `${+m.thickness_mm} mm`].filter(Boolean).join(' · ') || 'titanium' : 'titanium not specified');
  const setupName = (s) => [laserName(s.laser), lensName(s.lens), s.material ? materialName(s.material) : null].filter(Boolean).join(' · ');
  const releaseName = (r) => `release dated ${day(r.release_created_at || r.created_at)} · ${short(r.content_sha256)}`;
  const BASIS = {chart: 'reference chart corrected', clean: 'relative to clean titanium', 'as-shot': 'as photographed, unreferenced'};
  const hexChip = (hex) => (hex ? h('span', {class: 'sw', style: `background:${hex}`, title: hex}) : h('span', {class: 'sw ge-none', title: 'color not measured'}));
  const chipOf = (c) => (c ? h('span', {}, swatch(c.lab), labText(c.lab)) : h('span', {class: 'muted'}, 'not measured'));

  /** Choose local measurements by default or a setup from a connected lab release. */
  function picker(kind, {onChange = null} = {}) {
    const select = h('select', {'aria-label': 'Measurement source'}, h('option', {value: ''}, 'My measurements'));
    const hint = h('span', {class: 'small muted'}, 'default: this workshop’s measurements');
    const options = [];                                    // option value n → {lab, setup}
    const chosen = () => (select.value === '' ? null : options[+select.value - 1] || null);
    const value = () => {
      const c = chosen();
      if (!c) return null;
      const out = {release_id: c.lab.release.release_id, laser: c.setup.laser.uuid, lens: c.setup.lens ? c.setup.lens.uuid : null};
      if (kind === 'vector') out.material = c.setup.material.uuid;
      return out;
    };
    const loaded = get('/labs/choices').then((labs) => {
      for (const lab of labs) {
        for (const setup of lab.setups) {
          if (kind === 'vector' && !setup.material) continue;
          options.push({lab, setup});
          select.append(h('option', {value: String(options.length)}, `${lab.name}: ${setupName(setup)} (photos ${setup.photographs})`));
        }
      }
      if (!options.length) hint.textContent = 'no connected labs with measurements; using this workshop’s measurements';
    }).catch(() => { hint.textContent = 'connected labs are unavailable; using this workshop’s measurements'; });
    select.addEventListener('change', () => {
      const c = chosen();
      fill(hint, c ? [`${c.lab.name}, ${releaseName(c.lab.release)}`, c.lab.release.verified ? null : ' · signature not verified',
        '. Colors and curves were measured by another lab on its laser; the same color is not guaranteed on this laser.'] : 'default: this workshop’s measurements');
      if (onChange) onChange(value());
    });
    const el = h('label', {class: 'f'}, h('span', {}, 'Measurement source'), select, hint);
    return {el, select, hint, value, chosen, loaded};
  }

  // ---- the source of an open work ------------------------------------------------------------------------------------------------

  /** The conditions of a work's source, each translated; the frozen reason is shown apart and left out here. */
  const conditionList = (s) => (s.conditions || []).filter((c) => c !== s.frozen).map((c) => h('li', {}, I18N.tr(c)));

  /** Show a pinned release source and preview any update or return to an earlier source. */
  function banner(base, kind, applied) {
    const el = h('div', {class: 'lab-banner alert', role: 'note', 'aria-label': 'Work measurement source', hidden: true});
    function update(work) {
      const s = work && work.source;
      el.hidden = !s || s.kind !== 'release';
      if (el.hidden) return fill(el);
      const conditions = conditionList(s);
      return fill(el,
        h('div', {class: 'row lab-banner-head'}, h('strong', {}, 'Source: laboratory '), h('span', {class: 'lab-name'}, s.lab_name), pill(releaseName(s)),
          s.withdrawn_hidden ? pill(`withdrawn measurements excluded: ${s.withdrawn_hidden}`, 'warn') : null),
        h('p', {class: 'small lab-setup'}, `${laserName(s.laser)} · ${lensName(s.lens)} · ${materialName(s.material)}`
          + (s.pinned_at ? ` · pinned ${when(s.pinned_at)}` : '') + (s.versions ? ` · previous sources: ${s.versions}` : '')),
        conditions.length ? h('ul', {class: 'small lab-conditions'}, conditions) : null,
        s.frozen ? h('p', {class: 'alert bad lab-frozen', role: 'alert'}, h('strong', {}, 'Result frozen. '), I18N.tr(s.frozen)) : null,
        work.confirmed ? h('p', {class: 'small'}, 'Confirmed file: ', h('a', {href: work.confirmed.file}, work.confirmed.name || 'LightBurn file'),
          ` · confirmed ${when(work.confirmed.at)}`) : null,
        h('div', {class: 'row'}, btn('Update source', () => step({}), 'btn-small'),
          s.versions > 0 ? btn('Return to previous source', () => step({back: true}), 'btn-small') : null));
    }
    async function step(request) {
      let preview;
      try { preview = await post(`${base}/source`, request); } catch (e) { return fail(e); }
      return previewDialog(preview, kind, request, async () => {
        const made = await post(`${base}/source`, {...request, confirm: true});
        toast(request.back ? 'Work returned to its previous source' : 'Work source updated', 'ok');
        applied(made.work);
      });
    }
    return {el, update};
  }

  /** Preview the destination and changes before confirmation. */
  function previewDialog(p, kind, request, confirm) {
    const to = p.to || {};
    const where = h('p', {}, request.back ? 'Work will return to source: ' : 'Work will move to source: ', h('strong', {}, to.lab_name),
      `, ${releaseName(to)}; ${laserName(to.laser)} · ${lensName(to.lens)}` + (to.material ? ` · ${materialName(to.material)}` : '')
      + (to.withdrawn_hidden ? `; withdrawn measurements excluded: ${to.withdrawn_hidden}` : ''));
    return modal(request.back ? 'Return to previous source' : 'Update work source', h('div', {class: 'stack lab-preview'}, where,
      to.frozen ? h('p', {class: 'alert bad'}, I18N.tr(to.frozen)) : null,
      kind === 'vector' ? vectorPreview(p) : photoPreview(p),
      h('p', {class: 'small muted'}, 'The work remains unchanged until confirmed. The previous source is retained so you can return to it.')), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Confirm', cls: 'primary', run: async (m) => { await confirm(); m.close(); }}]);
  }

  /** What the step does to the colours of a vector work: a colour a line (was → will be, ΔE), the colours that go missing and the largest
      changes first, by pages (a work may hold dozens of colours, DEC-090). */
  function vectorPreview(p) {
    const entries = p.entries || [];
    const change = (e) => (e.missing ? 'missing' : e.delta_e > 0 ? 'changed' : 'same');
    const colours = entries.length ? App.list({items: entries,
      row: (e) => [chipOf(e.before), h('span', {class: 'muted'}, '→'), chipOf(e.after),
        e.missing ? pill('not measured in new source', 'bad') : e.delta_e == null ? h('span', {class: 'muted'}, 'ΔE —')
          : e.delta_e > 0 ? h('span', {}, `ΔE ${num(e.delta_e, 1)}`) : pill('unchanged', 'ok')],
      filters: [{key: 'change', label: 'Color change', options: [['missing', 'missing'], ['changed', 'changed'], ['same', 'unchanged']],
        test: (e, v) => change(e) === v}],
      sorts: [['largest', 'Largest changes first', (a, b) => (b.missing ? 1 : 0) - (a.missing ? 1 : 0) || (b.delta_e ?? -1) - (a.delta_e ?? -1)],
        ['work', 'Work order']]}).el : h('p', {class: 'muted'}, 'The work does not yet use source colors');
    const zones = p.zones || [];
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, `Colors in work: ${entries.length}; changed: ${p.changed || 0}; missing: ${p.missing || 0}`
        + (p.max_delta_e != null ? `; largest difference ΔE ${num(p.max_delta_e, 1)}` : '') + '.'),
      colours,
      zones.length ? h('div', {}, h('p', {class: 'small'}, 'Photo zones:'),
        h('ul', {class: 'small'}, zones.map((z) => h('li', {}, `zone ${z.zone}: `, z.problem ? I18N.tr(z.problem) : 'scale measured in the new source')))) : null);
  }

  function photoPreview(p) {
    if (p.problem) return h('p', {class: 'alert warn'}, I18N.tr(p.problem));
    const rows = (p.steps || []).map((s) => [num(s.power, 1), hexChip(s.before), hexChip(s.after), s.delta_e == null ? '—' : num(s.delta_e, 1)]);
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, p.max_delta_e != null ? `Largest scale color difference from Min to Max: ΔE ${num(p.max_delta_e, 1)}.` : 'The scale colors could not be compared.'),
      table(['Power, %', 'Before', 'After', 'ΔE'], rows, 'Scale not compared', true));
  }

  return {picker, banner, previewDialog, short, day, when, laserName, lensName, materialName, setupName, releaseName, BASIS, hexChip};
})();
