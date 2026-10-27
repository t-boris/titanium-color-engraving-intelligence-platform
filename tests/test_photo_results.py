"""Human outcomes stay with the engraved file, are visible when selecting settings, and outrank a misleading automatic score."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_photo_knowledge import world, accepted, layer, LINEAR, NEGATIVE  # noqa: F401
from titanium_platform import photo_results as results, photo_knowledge as pk, prediction_store as ps, setup as su
from titanium_platform.api import routes_photo_knowledge
from titanium_platform.api.common import install_error_handlers


def mode(w, pulse=200):
    return ps.Mode(w['laser'], w['lens'], w['titanium'], 125, 60, pulse, .01, 1)


def add_photo(w, name, levels, pulse=200):
    rep = layer(name, 'grayscale', levels, power=30, min_power=2, pulse=pulse)
    rep['tonal']['power_range'] = [2, 30]
    ident = accepted(w, [rep])
    w['store'].execute('UPDATE pair SET engraving_id=? WHERE id=?', (f'PHYSICAL-{ident}', ident))
    return ident


def test_manual_good_beats_a_better_automatic_score_and_bad_is_not_recommended(world):
    w, s = world, world['store']
    good = add_photo(w, 'Luna', NEGATIVE, pulse=300)
    other = add_photo(w, 'Automatic favourite', LINEAR)
    assert pk.best(s, w['laser'], w['lens'], w['titanium'], 'grayscale')['source']['pair_id'] == other
    before = s.one('SELECT data_json FROM pair WHERE id=?', (good,))['data_json']
    row, = results.at_mode(s, mode(w, 300))
    saved = results.mark(s, row['source'], 'good', 'Excellent colour photograph')
    assert saved['settings']['pulse_width'] == 300
    assert pk.best(s, w['laser'], w['lens'], w['titanium'], 'grayscale')['source']['pair_id'] == good
    summary = ps.scale(s, mode(w, 300))
    assert summary['results']['good'] == 1 and summary['examples'][0]['note'] == 'Excellent colour photograph'
    results.mark(s, row['source'], 'bad', 'Details lost')
    assert pk.best(s, w['laser'], w['lens'], w['titanium'], 'grayscale')['source']['pair_id'] == other
    assert s.one('SELECT data_json FROM pair WHERE id=?', (good,))['data_json'] == before  # measured observations were not rewritten
    results.mark(s, row['source'], 'unrated')
    assert results.at_mode(s, mode(w, 300))[0]['verdict'] == 'unrated'


def test_mark_api_validates_the_source_and_keeps_a_note_per_actual_layer(world):
    w, s = world, world['store']
    add_photo(w, 'Luna', LINEAR)
    row, = results.at_mode(s, mode(w))
    app = FastAPI(); app.state.store = s; app.include_router(routes_photo_knowledge.router); install_error_handlers(app)
    client = TestClient(app)
    answer = client.post('/api/photo-results/mark', json={'source': row['source'], 'verdict': 'bad', 'note': 'Too pale'})
    assert answer.status_code == 200 and answer.json()['note'] == 'Too pale'
    assert results.at_mode(s, mode(w))[0]['verdict'] == 'bad'  # catalog invalidation on mark
    for body in ({'source': row['source'], 'verdict': 'perfect'},
                 {'source': {**row['source'], 'engraving_id': 'another-workshop'}, 'verdict': 'good'},
                 {'source': row['source'], 'verdict': 'good', 'note': 'x' * 1001}):
        assert client.post('/api/photo-results/mark', json=body).status_code == 422
    assert results.at_mode(s, mode(w))[0]['verdict'] == 'bad'


def test_rephotographing_one_engraving_does_not_double_the_success_count(world):
    w, s = world, world['store']
    ident = add_photo(w, 'Luna', LINEAR)
    row, = results.at_mode(s, mode(w))
    results.mark(s, row['source'], 'good')
    another = add_photo(w, 'Luna again', LINEAR)
    engraving = s.one('SELECT engraving_id FROM pair WHERE id=?', (ident,))['engraving_id']
    s.execute('UPDATE pair SET engraving_id=? WHERE id=?', (engraving, another))
    assert results.summary(results.at_mode(s, mode(w))) == {'good': 1, 'bad': 0, 'unrated': 0, 'total': 1}


def test_colour_success_does_not_turn_a_failed_photo_layer_into_a_success(world):
    w, s = world, world['store']
    add_photo(w, 'C23', LINEAR)
    row, = results.at_mode(s, mode(w))
    results.mark(s, row['source'], 'bad', 'Photo is washed out', aspect='photo')
    results.mark(s, row['source'], 'good', 'Gold colour is correct', aspect='colour')
    found, = results.at_mode(s, mode(w))
    assert found['verdict'] == 'bad'
    assert found['assessments'] == {'photo': {'verdict': 'bad', 'note': 'Photo is washed out'},
                                    'colour': {'verdict': 'good', 'note': 'Gold colour is correct'}}
    assert pk.best(s, w['laser'], w['lens'], w['titanium'], 'grayscale') is None
