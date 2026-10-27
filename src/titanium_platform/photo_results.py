"""Operator outcomes per LightBurn marker/layer and aspect (colour or photo engraving), independent of measured colour observations and automatic tonal scores.

A mark belongs to one photo layer of an accepted pair or a numbered export, never to the work's mutable current settings.
Unsuccessful measurements remain available to the prediction model. A report without a photograph is explicitly labelled as such.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from . import lightburn as lb, photo_knowledge as pk, plans, prediction_store as ps, row_length, setup as su
from .db import Store, now


def marks(store: Store, aspect: str = 'photo') -> dict:
    if store.one("SELECT name FROM sqlite_master WHERE type='table' AND name='photo_result_mark'") is None:
        return {}
    return {r['source_key']: {**json.loads(r['snapshot_json']), 'aspect': r['aspect'], 'verdict': r['verdict'], 'note': r['note'], 'updated_at': r['updated_at']}
            for r in store.query('SELECT * FROM photo_result_mark WHERE aspect=?', (aspect,))}


def pair_key(pair, layer: int) -> str:
    return f"engraving:{pair['engraving_id']}:{layer}"


def _pair_rows(store: Store, pair_id: int | None = None) -> list[dict]:
    rows = store.query("SELECT * FROM pair WHERE status='Accepted'" + (' AND id=?' if pair_id is not None else ''),
                       (pair_id,) if pair_id is not None else ())
    out = []
    for pair in rows:
        data = json.loads(pair['data_json'] or '{}')
        for rep in (data.get('check') or {}).get('layers', []):
            if (rep.get('tonal') or {}).get('measured_by') == 'grey ramp':
                continue
            settings = pk.settings_of(rep)
            if settings is None:
                continue
            out.append({'source': {'kind': 'pair', 'id': pair['id'], 'layer': rep['index'], 'engraving_id': pair['engraving_id']},
                        'key': pair_key(pair, rep['index']), 'title': pair['engraving_title'] or pair['lightburn_name'],
                        'device_id': pair['device_id'], 'lens_id': pair['lens_id'], 'material_id': pair['material_id'],
                        'settings': settings, 'layer': rep.get('name') or f"C{rep['index']:02d}",
                        'width_mm': row_length.of_file(pair['lightburn_path']).get(rep['index']),
                        'photo': f"/api/pairs/{pair['id']}/photo.png?corrected=true&size=360",
                        'url': f"#/analysis/{pair['id']}", 'photo_name': pair['photo_name'], 'at': pair['accepted_at'],
                        'automatic_score': (rep.get('photo_quality') or {}).get('score'), 'without_photo': False})
    return out


def export_rows(store: Store, plan_id: int, number: int | None = None) -> list[dict]:
    plan = plans.get_plan(store, plan_id)
    exports = plan.get('exports') or []
    if number is not None:
        exports = [e for e in exports if e['number'] == number]
    else:
        exports = exports[-5:]
    out = []
    for export in reversed(exports):
        path = Path(export.get('path') or '')
        if not path.is_file():
            continue
        raw = path.read_bytes()
        project = lb.parse_bytes(raw)
        widths = row_length.of_file(str(path))
        for layer in project.layers:
            if layer.layer_type != 'Image':
                continue
            image = layer.image_summary()
            rep = {'image': image, 'power': layer.power, 'speed': layer.speed,
                   'frequency_khz': layer.frequency_hz / 1000 if layer.frequency_hz is not None else None,
                   'pulse_width': layer.pulse_width, 'line_interval': layer.line_interval,
                   'passes': layer.passes, 'global_passes': layer.global_passes}
            settings = pk.settings_of(rep)
            if settings is None or layer.output_off:
                continue
            zone = next((z for z in export.get('zones') or [] if z['index'] == layer.index), {})
            out.append({'source': {'kind': 'export', 'id': plan_id, 'number': export['number'], 'layer': layer.index,
                                   'sha256': hashlib.sha256(raw).hexdigest()},
                        'key': f"export:{plan_id}:{export['number']}:{layer.index}",
                        'title': f"{plan['name']} · файл №{export['number']}", 'device_id': plan['device_id'], 'lens_id': plan['lens_id'],
                        'material_id': plan.get('material_id'), 'settings': settings, 'image': image,
                        'zone': zone.get('number'), 'zone_regions': zone.get('regions'),
                        'processing': {k: zone.get(k) for k in ('by_colour', 'colour_choice', 'contours', 'tone', 'sharpness')},
                        'scan_angle': layer.scan_angle, 'bidirectional': layer.bidirectional, 'layer': layer.name,
                        'width_mm': widths.get(layer.index), 'file_sha256': hashlib.sha256(raw).hexdigest(),
                        'photo': None, 'url': f"#/vector?plan={plan_id}", 'photo_name': None, 'at': export.get('at'),
                        'automatic_score': None, 'without_photo': True})
    return out


def _marked(row: dict, found: dict, colours: dict | None = None) -> dict:
    mark = found.get(row['key'])
    colour = (colours or {}).get(row['key'])
    assessment = lambda m: {k: (m or {}).get(k, 'unrated' if k == 'verdict' else '') for k in ('verdict', 'note')}
    return {**row, **(mark or colour or {}), 'verdict': mark['verdict'] if mark else 'unrated', 'note': mark['note'] if mark else '',
            'updated_at': mark.get('updated_at') if mark else None,
            'assessments': {'photo': assessment(mark), 'colour': assessment(colour)}}


def for_work(store: Store, plan_id: int, zone: int | None = None) -> list[dict]:
    found, colours = marks(store), marks(store, 'colour')
    return [_marked(row, found, colours) for row in export_rows(store, plan_id) if zone is None or row.get('zone') == zone]


def at_mode(store: Store, mode: ps.Mode) -> list[dict]:
    rows = _catalog(store, store.stamp())
    materials = su.same_titanium(store, mode.material_id) if mode.material_id else [None]
    out = [r for r in rows if r['device_id'] == mode.device_id and r['lens_id'] == mode.lens_id
           and r['material_id'] in materials and r['settings']['dither'] == mode.dither and mode.matches(r['settings'])]
    return sorted(out, key=lambda r: ({'good': 0, 'unrated': 1, 'bad': 2}[r['verdict']], r['title'], r['key']))


@lru_cache(maxsize=8)
def _catalog(store: Store, stamp: tuple) -> tuple:
    found, colours = marks(store), marks(store, 'colour')
    rows = _pair_rows(store) + [r for r in {**colours, **found}.values() if r['source']['kind'] == 'export']
    return tuple(_marked(r, found, colours) for r in {r['key']: r for r in rows}.values())


def summary(rows: list[dict]) -> dict:
    return {v: sum(r['verdict'] == v for r in rows) for v in ('good', 'bad', 'unrated')} | {'total': len(rows)}


def mark(store: Store, source: dict, verdict: str, note: str = '', aspect: str = 'photo') -> dict:
    if aspect not in ('photo', 'colour'):
        raise su.ValidationError('choose photo engraving or colour for this layer assessment')
    if verdict not in ('good', 'bad', 'unrated'):
        raise su.ValidationError('choose good, bad or unrated for the engraving result')
    if not isinstance(note, str) or len(note.strip()) > 1000:
        raise su.ValidationError('the engraving result note must be at most 1000 characters')
    if not isinstance(source, dict) or source.get('kind') not in ('pair', 'export'):
        raise su.ValidationError('choose an accepted photo or a numbered exported file for the result')
    try:
        kind, ident, layer = source['kind'], int(source['id']), int(source['layer'])
        rows = _pair_rows(store, ident) if kind == 'pair' else export_rows(store, ident, int(source['number']))
        row = next(r for r in rows if r['source']['layer'] == layer)
        identity = 'engraving_id' if kind == 'pair' else 'sha256'
        if source.get(identity) != row['source'][identity]:
            raise ValueError('the source changed or belongs to another workshop')
    except (KeyError, TypeError, ValueError, StopIteration, OSError):
        raise su.ValidationError('the engraved photo layer of this result is unavailable') from None
    at = now()
    with store.transaction():
        store.execute('INSERT INTO photo_result_mark(source_key,aspect,verdict,note,snapshot_json,updated_at) VALUES(?,?,?,?,?,?) '
                      'ON CONFLICT(source_key,aspect) DO UPDATE SET verdict=excluded.verdict,note=excluded.note,snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at',
                      (row['key'], aspect, verdict, note.strip(), json.dumps(row, ensure_ascii=False), at))
        store.audit('photo_result_marked', source=row['source'], aspect=aspect, verdict=verdict, note=note.strip())
    return {**row, 'aspect': aspect, 'verdict': verdict, 'note': note.strip(), 'updated_at': at}
