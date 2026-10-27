"""Inna & Emmy 2: a large brown fill must replace its small green prediction, and a failed photo must teach its preview."""
import copy
import json

import cv2
import numpy as np
import pytest

import obs
from test_palette import world, partition  # noqa: F401
from test_prediction_store import w, mode, pair, tonal_check  # noqa: F401
from test_vector_work import work, job  # noqa: F401
from test_work_review import layer, seen
from titanium_platform import ingest, lightburn as lb, palette, plans, prediction_store as ps, row_length, vector_job as vj, work_errors as we
from titanium_platform.db import now


def test_fill_evidence_reaches_existing_choices_across_task_and_lightburn_default_without_losing_ids(store, world):
    def add(lab, task, source, width):
        oid = obs.add(store, world, lab, material_id=world['ti'], layer_type='Scan', task_kind=task,
                      lightburn={'source_settings': source})
        pid = store.one('SELECT pair_id FROM observation WHERE id=?', (oid,))['pair_id']
        store.execute('INSERT INTO pair_row_length(pair_id,layer_index,row_mm) VALUES (?,?,?)', (pid, 1, width))
        return oid
    first = add([59, -6, 30], 'fill', {}, 5)
    before = partition(store, world)['entries'][0]
    second = add([53, 12, 26], 'color_image', {'fgPathAlgorithm': {'Value': 'CutGantry'}}, 50)
    entries = partition(store, world)['entries']
    kept = next(e for e in entries if e['id'] == before['id'])
    assert kept['observation_ids'] == [first, second]
    assert palette.at_size(kept, 50)['lab'] == [53, 12, 26]
    assert palette.at_size(kept, 5)['lab'] == [59, -6, 30]
    assert len(palette.choosable(entries, None, False)[0]) == 1  # saved aliases remain, automatic choices use one physical recipe
    assert store.one('SELECT task_kind FROM observation WHERE id=?', (first,))['task_kind'] == 'fill'
    assert store.one('SELECT task_kind FROM observation WHERE id=?', (second,))['task_kind'] == 'color_image'


@pytest.mark.parametrize('extra', [{'fgPathAlgorithm': {'Value': 'OtherAlgorithm'}}, {'unknownHeatControl': {'Value': '1'}},
                                  {'scanOpt': {'Value': 'individual'}}])
def test_other_or_unknown_execution_controls_are_never_merged(store, world, extra):
    for lab, source in [([59, -6, 30], {}), ([53, 12, 26], extra)]:
        obs.add(store, world, lab, material_id=world['ti'], layer_type='Scan', lightburn={'source_settings': source})
    entries = partition(store, world)['entries']
    assert len(entries) == 2 and all(e['engravings'] == 1 for e in entries)


def test_vector_preview_uses_the_recipe_fill_order_and_matches_the_export(work, job):
    s = work['store']
    p = plans.get_plan(s, job['id'])
    entries = vj._palette(s, p)
    for e in entries:
        e['parameters']['source_settings'] = {'scanOpt': {'Value': 'individual'}}
    state = vj._state(p, vj._document(p), entries)
    for layer in state['layers']:
        geometry = vj._joined(vj._document(p), {rid: 'same' for rid in layer['region_ids']})
        from titanium_platform import segment
        shapes = [r['loops'] for r in segment.regions_as_loops(geometry) if r['id'] in layer['region_ids']]
        assert layer['row_mm'] == row_length.of_shapes(shapes, together=False)


def test_export_selection_includes_photos_and_respects_min_power_and_pulse():
    promise = [layer(1)]
    a = {'layer_type': 'Image', 'dither': 'grayscale', 'power': 30, 'min_power': 1, 'speed': 150, 'frequency': 60,
         'pulse_width': 250, 'line_interval': 0.0212, 'passes': 1}
    b = {**a, 'pulse_width': 350, 'min_power': 2.9, 'power': 28.2}
    p = {'exports': [{'number': 2, 'promised': promise, 'zones': [{'parameters': a}]},
                     {'number': 3, 'promised': promise, 'zones': [{'parameters': b}]}]}
    engraved = [seen(1), {'settings': a}]
    assert we._promise_for(p, engraved)[0] == 2
    assert we._promise_for(p, [seen(1), {'settings': b}])[0] == 3


def test_a_weak_profile_is_used_only_when_our_exact_export_proves_the_bitmap_orientation(w, tmp_path):
    image = np.tile(np.arange(64, dtype=np.uint8) * 4, (32, 1))
    settings = {**ps.mode_of({'speed': 128, 'frequency': 60, 'pulse_width': 300, 'line_interval': .0169, 'passes': 1}, 1, 1, 1).as_dict(),
                'power': 16, 'min_power': 5}
    path = tmp_path / 'export.lbrn2'
    path.write_bytes(plans.export_picture(image, 40, settings, 'own export', clean=None))
    saved = {'strategy': 'photo', 'export_mirror_y': True, 'exports': [{'path': str(path)}]}
    pid = w['store'].execute('INSERT INTO plan(name,mode,status,device_id,lens_id,data_json,created_at) VALUES (?,?,?,?,?,?,?)',
                           ('test', plans.MODE_VECTOR, 'Exported', w['laser']['id'], w['lens']['id'], json.dumps(saved), now())).lastrowid
    check = tonal_check(evidence='weak')
    check['layers'][0]['tonal']['vertical_flip'] = False
    pair_id = pair(w, check=check, plan_id=pid)
    w['store'].execute('UPDATE pair SET lightburn_path=? WHERE id=?', (str(path), pair_id))
    assert len(ps.collect(w['store'], mode(w))['points']) == 3
    # An edited bitmap, a wrong orientation or a merely similar filename cannot admit the weak profile.
    edited = tmp_path / 'edited.lbrn2'
    edited.write_bytes(plans.export_picture(255-image, 40, settings, 'own export', clean=None))
    w['store'].execute('UPDATE pair SET lightburn_path=? WHERE id=?', (str(edited), pair_id))
    assert ps.collect(w['store'], mode(w))['points'] == []
    check['layers'][0]['tonal']['vertical_flip'] = True
    w['store'].execute('UPDATE pair SET lightburn_path=?,data_json=? WHERE id=?', (str(path), json.dumps({'check': check}), pair_id))
    assert ps.collect(w['store'], mode(w))['points'] == []


def test_thumbnail_reads_current_measurements_even_when_saved_layers_are_stale(work, job):
    s = work['store']
    before = vj.thumbnail(s, job['id'])
    p = plans.get_plan(s, job['id'])
    old = copy.deepcopy(p['layers'])
    target = old[0]
    params = target['parameters']
    obs.add(s, work['w'], [25, 2, 2], power=params['power'], frequency=params['frequency'], speed=params['speed'],
            pulse_width=params['pulse_width'], line_interval=params['line_interval'], passes=params['passes'],
            material_id=work['ti'], layer_type=params['layer_type'])
    assert vj.thumbnail(s, job['id']).key != before.key
    assert plans.get_plan(s, job['id'])['layers'] == old


def test_review_photo_keeps_its_placement_and_alpha_instead_of_turning_the_face_upside_down(store, monkeypatch):
    settings = {'speed': 150, 'frequency': 60, 'pulse_width': 250, 'line_interval': .0212, 'passes': 1, 'power': 30, 'min_power': 1}
    pixels = np.full((64, 64, 4), 210, np.uint8)
    pixels[..., 3] = 0
    pixels[:24, :32, 3] = 255  # the only engraved patch is at the top left
    project = lb.parse_bytes(plans.export_picture(pixels, 40, settings, 'photo', clean=None))
    layer = project.layers[0]
    region = layer.regions[0]
    region.x = region.y = 0
    region.bitmap['matrix'] = (1, 0, 0, 1, 20, 20)
    region.bitmap['png'] = cv2.imencode('.png', pixels)[1].tobytes()
    rep = {'index': layer.index, 'tonal': {'vertical_flip': False, 'bins': [
        {'gray': .1, 'L': 30, 'a': 0, 'b': 0}, {'gray': .9, 'L': 90, 'a': 0, 'b': 0}]}}
    pair_ = {'id': 1, 'lightburn_path': '/not-read', 'check': {'layers': [rep]}}
    monkeypatch.setattr(we.ingest, 'get_pair', lambda *a: pair_)
    monkeypatch.setattr(we.lb, 'parse_file', lambda *a: project)
    photo = {'index': layer.index, 'settings': {**settings, 'dither': 'grayscale'}, 'bands': []}
    plan = {'id': 1, 'export_mirror_y': False}
    pictures = we._review_pictures(store, plan, {'pair_id': 1, 'photo': [photo]}, False)
    assert len(pictures) == 1
    box, pic = pictures[0]
    rgba = cv2.imdecode(np.frombuffer(pic.png(), np.uint8), cv2.IMREAD_UNCHANGED)
    assert box == {'x': 0, 'y': 0, 'width': 40, 'height': 40}
    assert rgba[:200, :200, 3].mean() > 250
    assert rgba[600:, :, 3].max() == 0 and rgba[:, 600:, 3].max() == 0


def test_photo_review_explains_the_wrong_export_and_the_actual_tones_in_the_ui(tmp_path):
    from test_work_review_ui import run
    review = {'engraving_id': 'e1', 'photo_name': 'result.DNG', 'reviewed_at': '2026-10-27T06:55:00', 'export_number': 2,
              'summary': {'matched': 0, 'promised': 0}, 'rows': [], 'notes': [], 'not_engraved': [], 'unmatched': [],
              'photo': [{'zone': 1, 'changed_settings': ['pulse_width', 'min_power'], 'latest_export': 3,
                         'settings': {'pulse_width': 250, 'min_power': 1}, 'latest_settings': {'pulse_width': 350, 'min_power': 2.9},
                         'median_de': 18, 'max_de': 61, 'profile_usable': True,
                         'tone': {'levels': 10, 'steps': 15, 'black_L': 46, 'white_L': 88.4}}]}
    out = run(tmp_path, {'job': {'id': 46, 'reviews': [review]}}, "out.text = VR.view(data.job, run).textContent;")
    assert 'Фотозона 1' in out['text'] and '250 → 350' in out['text'] and '1 → 2.9' in out['text']
    assert '18' in out['text'] and '61' in out['text'] and '46' in out['text'] and '88.4' in out['text']
    assert 'undefined' not in out['text'] and 'участвуют в следующих прогнозах' in out['text']


def test_comparison_of_an_old_engraving_keeps_its_exported_split_size_and_smoothing_after_edits(work, job):
    from test_work_review import engrave, exported
    s, client = work['store'], work['client']
    exported(work, job)
    pid = engrave(work, job)
    we.record(s, pid)
    original = {p: we.engraved_picture(s, job['id'], 'eng-1', p).png() for p in (False, True)}
    response = client.post(f"/api/vector/{job['id']}/split", json={'n_colors': 3, 'faces': False, 'density': 40})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/vector/{job['id']}/size", json={'width_mm': 40})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/vector/{job['id']}/smoothing", json={'mm': .3})
    assert response.status_code == 200, response.text
    current = plans.get_plan(s, job['id'])
    assert current['document_version'] != current['exports'][0]['document_version']
    for p in (False, True):
        assert we.engraved_picture(s, job['id'], 'eng-1', p).png() == original[p]
    assert plans.get_plan(s, job['id']) == current
