"""BUG-011: a scale chosen for a picture must show that picture's size and power interval, including unmeasured colours."""
import json

import numpy as np

from test_grey_scales import app_world  # noqa: F401
from test_prediction_store import MODE, mode, pair, tonal_check, w  # noqa: F401
from test_photo_engraving_ui import node, run as work_screen, scale_answer
from test_vector_zone_ui import run as zone_screen
from titanium_platform import plans, prediction_store as ps


def test_the_scale_list_uses_the_requested_size_instead_of_the_default_short_colourful_probe(w, tmp_path):
    short = [(0.25, [30, 0, 0]), (0.5, [45, 10, -25]), (0.75, [55, 5, -35])]
    long = [(0.25, [45, 0, 0]), (0.5, [70, 0, 15]), (0.75, [90, 0, 20])]
    for width, bins in [(40, short), (40, short), (120, long)]:
        pid = pair(w, check=tonal_check(bins, chart=True))
        path = tmp_path / f'probe-{width}.lbrn2'
        path.write_bytes(plans.export_picture(np.full((16, 64), 127, np.uint8), width,
            {**MODE, 'power': 16, 'min_power': 5}, clean=None))
        w['store'].execute('UPDATE pair SET lightburn_path=? WHERE id=?', (str(path), pid))
    default, = ps.scales(w['store'])
    at_work, = ps.scales(w['store'], row_mm=120)
    assert default['size']['from_mm'] == [40]
    assert at_work['size']['from_mm'] == [120]
    assert default['bar'][0]['hex'] == ps._hex(short[-1][1])
    assert at_work['bar'][0]['hex'] == ps._hex(long[-1][1])
    assert at_work['bar'] != default['bar']
    detail = ps.scale(w['store'], mode(w), row_mm=120)
    assert at_work['bar'] == detail['bar'] and at_work['size'] == detail['size']


def test_the_api_lists_scale_colours_at_the_same_width_as_the_picture_detail(app_world):
    client = app_world['client']
    query = {**app_world['mode'], 'row_mm': 121.4}
    listed = client.get('/api/grey-scales', params={'device_id': query['device_id'], 'row_mm': 121.4})
    assert listed.status_code == 200
    sc = next(s for s in listed.json()['scales'] if all(s['mode'][key] == query.get(key, 1) for key in ps.SETTINGS))
    detail = client.get('/api/grey-scales/scale', params=query).json()
    assert sc['size']['row_mm'] == 121.4
    assert sc['size'] == detail['size'] and sc['bar'] == detail['bar']


def response(width, low=12, high=28):
    d = scale_answer()
    d['size'] = {'row_mm': width, 'how': 'measured', 'from_mm': [width], 'measured_mm': [38.4, width]}
    for row in d['greys']['levels']:
        row['power'] = low + (high - low) * (1 - row['level'] / 255)
        row['hex'] = None if row['level'] < 15 or row['level'] > 240 else '#e2d7ae' if row['level'] > 128 else '#626c70'
    d['greys']['measured_levels'] = 226
    return d


SNAPSHOT = """
  const snapshot = () => {
    const card = tree.querySelector('.ge-scale.is-chosen');
    const bands = (el) => el.querySelectorAll('span').map((s) => [s.getAttribute('style'), s.className, s.getAttribute('title')]);
    return {card: bands(card.querySelector('.ge-bar')), preview: bands(tree.querySelector('.ge-barbox').querySelector('.ge-strip')),
      ends: card.querySelector('.ge-ends').textContent, text: card.textContent};
  };
  out.before = snapshot();
"""


@node
def test_a_zone_selected_card_matches_the_preview_colours_unknowns_and_updated_power_range(tmp_path):
    changed = json.dumps(response(24.5, 12, 20))
    result = zone_screen(tmp_path, SNAPSHOT + """
  data.scale = %s;
  const max = labelled(tree, 'Max мощность, %% (чёрный)');
  max.value = '20'; await max.dispatch('change'); await wait(300); await settle();
  out.after = snapshot();
""" % changed, scale_data=response(24.5))
    for name in ['before', 'after']:
        assert result[name]['card'] == result[name]['preview']
        assert len(result[name]['card']) == 64
        assert any(c[1] == 'ge-none' for c in result[name]['card'])
    assert result['before']['ends'] == 'P 12 %P 28 %'
    assert result['after']['ends'] == 'P 12 %P 20 %'
    assert 'Цвета при ширине 24,5 мм' in result['after']['text']


@node
def test_a_photo_work_reloads_choices_on_resize_and_uses_the_detail_for_its_selected_card(tmp_path):
    changed = json.dumps(response(120))
    result = work_screen(tmp_path, {'work': '7'}, SNAPSHOT + """
  data.scale = %s;
  data.scales = data.scales.map(s => ({...s, size: {...s.size, row_mm:120, from_mm:[120]}}));
  const width = labelled(tree, 'Ширина на титане, мм');
  width.value = '120'; await width.dispatch('change'); await settle();
  out.after = snapshot();
  out.widths = requests.filter(r => r.path === '/api/grey-scales').map(r => new URLSearchParams(r.url.split('?')[1]).get('row_mm'));
""" % changed, scale_data=response(60))
    assert result['widths'] == ['60', '120']
    for name in ['before', 'after']:
        assert result[name]['card'] == result[name]['preview']
    assert 'Цвета при ширине 120 мм' in result['after']['text']


@node
def test_a_late_palette_response_for_a_resized_work_cannot_overwrite_its_undo(tmp_path):
    at_120, at_60 = json.dumps(response(120)), json.dumps(response(60))
    result = work_screen(tmp_path, {'work': '7'}, SNAPSHOT + """
  const originalFetch = ctx.fetch;
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  ctx.fetch = async (url, options) => {
    const result = await originalFetch(url, options);
    if (String(url).startsWith('/api/grey-scales?') && new URLSearchParams(String(url).split('?')[1]).get('row_mm') === '120') await delayed;
    return result;
  };
  data.scale = %s;
  const width = labelled(tree, 'Ширина на титане, мм');
  width.value = '120'; await width.dispatch('change'); await settle();
  data.scale = %s;
  await button(tree, 'Отменить').dispatch('click'); await settle();
  out.undone = snapshot();
  release(); await settle();
  out.late = snapshot();
  out.width = labelled(tree, 'Ширина на титане, мм').value;
""" % (at_120, at_60), scale_data=response(60))
    assert result['width'] == '60'
    assert result['late'] == result['undone']
    assert result['late']['card'] == result['late']['preview']
    assert 'Цвета при ширине 60 мм' in result['late']['text']
