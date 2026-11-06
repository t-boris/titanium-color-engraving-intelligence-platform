/* Repeatability rules by laser and lens, and the marker layer (REQ-005, DEC-021, DEC-027, DEC-063). */
'use strict';
const SetupRules = (() => {
  const {h, btn, field, link, get, put, toast} = App;

  async function rulesTab(ctx, reload) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Add a laser first'), link('/devices', 'Lasers'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => reload('rules', pick.route())});
    const r = await get('/rules?' + pick.query());
    // the three thresholds are read as setup.save_rules reads them (a whole number from 1; two numbers that are not negative); an empty box stays unset,
    // a wrong one is said beside it and kept, and a refusal of the server stands above the button (ux-save-feedback-p0, REQ-003)
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const repField = form.add('repeat_threshold', 'Number of repeated engravings', Forms.numberInput(Q.repeatThreshold, {value: r.repeat_threshold ?? ''}), {quantity: 'repeatThreshold'});
    const tolField = form.add('delta_tolerance', 'Color difference tolerance', Forms.numberInput(Q.deltaTolerance, {value: r.delta_tolerance ?? ''}), {quantity: 'deltaTolerance'});
    const varField = form.add('variance_threshold', 'Allowed color variance', Forms.numberInput(Q.varianceThreshold, {value: r.variance_threshold ?? ''}), {quantity: 'varianceThreshold'});
    const agreed = h('input', {type: 'checkbox', checked: r.criteria_agreed});
    return h('div', {class: 'card stack'}, h('h3', {}, 'How repeatability is assessed'),
      h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Laser', pick.laser)), h('div', {class: 'f-wrap'}, field('Lens', pick.lens))),
      h('p', {class: 'muted small'}, 'Rules are separate for each laser and lens. Work with an unknown lens uses its own rules and is not mixed with other work.'),
      r.criteria_agreed
        ? h('div', {class: 'alert ok'}, 'Automatic promotion to Validated is enabled using the criteria below.')
        : h('div', {class: 'alert warn'}, 'Until criteria are agreed, records remain measured or repeated and are not promoted automatically.'),
      h('p', {class: 'muted'}, 'These rules only control automatic reliability assessment. They do not change laser settings, the LightBurn file or the color.'),
      h('ul', {class: 'muted small'},
        h('li', {}, 'Independent repeats are separate physical engravings of the same settings; another photograph of the same engraving does not count.'),
        h('li', {}, 'ΔE tolerance is the maximum acceptable color difference between repeats.'),
        h('li', {}, 'Variance threshold is an additional limit on color variation between repeats; lower means more stable.')),
      h('div', {class: 'grid g3'}, repField, tolField, varField),
      h('p', {class: 'muted small'}, 'With all three values set, a result can be marked Validated when enough independent engravings exist and both variation measures meet the thresholds. You choose the values; none are preset.'),
      h('label', {class: 'row'}, agreed, h('span', {}, 'Enable automatic assessment using these criteria')),
      form.error,
      h('div', {class: 'row'}, btn('Save thresholds', async () => {
        const v = form.collect();
        if (!v) return;
        try {
          await put('/rules', {device_id: pick.deviceId(), lens_id: pick.lensId(), ...v, criteria_agreed: agreed.checked});
          toast('Thresholds saved', 'ok'); reload('rules', pick.route());
        } catch (e) { form.fail(e); }
      }, 'primary'), link('/colors?' + pick.route(), 'Color model for this laser and lens')));
  }

  async function markersTab(reload) {
    const cur = await get('/marker-layer');
    // plans.save_marker_layer_settings: power, frequency and speed must be above 0 (and are required); the other three may stay empty (LightBurn then
    // takes its own value) and are above 0 when set, the passes a whole number from 1. The laser's own power and frequency range is judged
    // when a plate is made with them, not here (ux-save-feedback-p0, REQ-003)
    const form = Forms.create();
    const Q = Forms.QUANTITIES;
    const box = (quantity, value) => Forms.numberInput(Q[quantity], {value: value ?? ''});
    const power = form.add('power', 'Power', box('markerPower', cur?.power), {quantity: 'markerPower', required: true});
    const frequency = form.add('frequency', 'Frequency', box('markerFrequency', cur?.frequency), {quantity: 'markerFrequency', required: true});
    const speed = form.add('speed', 'Speed', box('markerSpeed', cur?.speed), {quantity: 'markerSpeed', required: true});
    const pulse = form.add('pulse_width', 'Q-Pulse (optional)', box('markerPulse', cur?.pulse_width), {quantity: 'markerPulse'});
    const interval = form.add('line_interval', 'Line spacing (optional)', box('markerInterval', cur?.interval), {quantity: 'markerInterval'});
    const passes = form.add('passes', 'Passes (optional)', box('markerPasses', cur?.passes), {quantity: 'markerPasses'});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Coded markers on the test plate'),
      h('p', {class: 'muted'}, 'This is neither the test pattern nor the cleaning layer. Four corner markers and an experiment QR code surround the matrix, helping align the photograph and identify the plate. They are excluded from color measurements.'),
      h('p', {class: 'muted small'}, 'In LightBurn these shapes are on a separate “Markers” layer (or “Markers and labels” with engraved labels on laser check plates), so it can be disabled. '
        + 'The settings below control how markers and labels are engraved on titanium; this layer follows mandatory cleaning and precedes the test cells. Plates with markers cannot be created until these settings are supplied.'),
      h('p', {class: 'muted small'}, 'Markers, labels and cleaning remain visible as evidence in the photograph, but never enter the color model or knowledge.'),
      cur ? null : h('div', {class: 'alert warn'}, 'Marker settings are not configured. Set them once and test them on titanium before automatic marker detection in photographs.'),
      h('div', {class: 'grid g3'}, power, frequency, speed),
      h('div', {class: 'grid g3'}, pulse, interval, passes),
      h('p', {class: 'muted small'}, 'Unset settings are omitted; LightBurn will use its own defaults.'),
      form.error,
      btn('Save coded marker settings', async () => {
        const v = form.collect();
        if (!v) return;
        try {
          await put('/marker-layer', v);
          toast('Marker layer saved', 'ok'); reload('markers');
        } catch (e) { form.fail(e); }
      }, 'primary'));
  }

  return {rulesTab, markersTab};
})();
