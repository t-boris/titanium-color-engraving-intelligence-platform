/* Pick a photo work or zone dot color from the matching laser and lens color map (DEC-118). */
'use strict';
const DotPick = (() => {
  const {h, btn, post, go, toast, fail} = App;
  const value = (v, d = 1) => (v == null ? '—' : String(+(+v).toFixed(d)));
  const kindName = (key) => { const t = PhotoModes.label(key); return t.charAt(0).toUpperCase() + t.slice(1); };
  const setupKey = (scale) => `laser:${scale.device_id}/lens:${scale.lens_id == null ? 'unknown' : scale.lens_id}`;

  /** Color-map route for a photo work and its laser and lens. */
  const address = (view) => `/colors?dots=${view.id}&setup=${encodeURIComponent(setupKey(view.scale))}`;
  /** Color-map route for a vector photo zone, optionally returning to its editor. */
  const zoneAddress = (work, number, from = null) => `/colors?dots=${work.id}&zone=${number}&setup=${encodeURIComponent(setupKey(work))}`
    + (from ? `&from=${from}` : '');
  /** Describe the selected work or zone, its return route and its save endpoint. */
  function owner(pick) {
    const w = pick.work;
    if (w.zone == null) return {name: `work “${w.name}”`, back: `/photo-engraving?work=${w.id}`, backText: '← Return to work without changes',
      save: `/photo-works/${w.id}/settings`, done: 'Dot color selected: the work will show dots in this color'};
    const editor = pick.from === 'editor';
    return {name: `photo zone ${w.zone} of work “${w.name}”`, back: editor ? `/vector?plan=${w.id}` : `/vector-zone?work=${w.id}&zone=${w.zone}`,
      backText: editor ? '← Return to work without changes' : '← Return to zone without changes', save: `/vector/${w.id}/photo/${w.zone}/settings`,
      done: 'Dot color selected: the zone will show dots in this color'};
  }
  /** Resolve a map color to a scale or fill, or a reason it is unavailable. */
  const of = (pick, point) => pick.groups[point.group] || {reason: null};
  const can = (pick, point) => !of(pick, point).reason && !!pick.groups[point.group];

  /** Identify the work and explain eligible colors and how to return. */
  function banner(pick) {
    const w = pick.work, who = owner(pick);
    const grade = w.material && w.material.grade ? `titanium ${w.material.grade}` : 'the work’s titanium';
    return h('div', {class: 'alert dp-banner', role: 'note'},
      h('div', {class: 'stack'},
        h('strong', {}, `Dot color for ${who.name} · ${kindName(w.kind)} · ${value(w.width_mm)} mm`),
        h('span', {class: 'small'}, 'Select a color on the map or find one on the right, then choose “Use for dots”. '
          + `Eligible colors use this laser and lens on ${grade}: gray-scale tones and fills with line spacing of at least ${value(pick.step_min_mm, 4)} mm. Other colors appear faded.`)),
      h('a', {class: 'btn btn-small', href: `#${who.back}`}, who.backText));
  }

  /** Describe the scale or fill settings the dots will use. */
  function what(found, point) {
    const p = point.parameters || {};
    const settings = `${value(p.speed)} mm/s · ${value(p.frequency)} kHz · ${p.pulse_width == null ? 'pulse not specified' : value(p.pulse_width, 0) + ' ns'} · spacing ${value(p.line_interval, 4)} mm`;
    return found.scale ? `Dots will use this gray scale at ${value(found.power)}%: ${settings}.`
      : `Dots will use this fill’s settings: ${value(p.power)}% · ${settings}; line spacing becomes dot spacing.`;
  }

  /** Offer the color selection or explain why the color cannot be used. */
  function action(pick, point) {
    const found = of(pick, point);
    if (!pick.groups[point.group]) return h('p', {class: 'small muted dp-action'}, 'This color cannot be used for dots: it uses a different laser or lens from the work.');
    if (found.reason) return h('p', {class: 'small muted dp-action'}, `This color cannot be used for dots: ${I18N.tr(pick.reasons[found.reason] || found.reason)}.`);
    const go_ = btn('Use for dots', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      self.textContent = 'Saving…';
      const who = owner(pick);
      try {
        await post(who.save, {dot_colour: point.group});
        toast(who.done, 'ok');
        go(who.back);
      } catch (e) { fail(e); self.disabled = false; self.textContent = 'Use for dots'; }
    }, 'primary btn-small');
    return h('div', {class: 'row dp-action'}, go_, h('span', {class: 'small muted'}, what(found, point)));
  }

  return {address, zoneAddress, can, banner, action};
})();
