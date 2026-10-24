"""A workshop with every kind of evidence a laboratory release carries (electron REQ-083..085), written straight into the store with
real LightBurn files on disk, so that the colour map, the palettes and the tonal curves read sizes and cleaning layers from those files.

Every private text is a marker (``MARKERS``): a release must carry none of them, in any encoding. Times and engraving ids are fixed, so
the results are the same on every run."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from titanium_platform import devices, lenses, plans as pl
from titanium_platform import setup as su
from titanium_platform.db import Store

MARKERS = ("MARKER-LASER-NAME", "MARKER-SERIAL-7781", "MARKER-LASER-DESCRIPTION", "MARKER-LENS-NAME", "MARKER-LENS-NOTE",
           "MARKER-MATERIAL-NAME", "MARKER-BATCH-17", "MARKER-SURFACE", "MARKER-TITLE", "MARKER-LBNAME", "MARKER-PHOTO",
           "MARKER-PATH", "MARKER-NOTE", "MARKER-DISCREPANCY", "MARKER-REASON", "MARKER-SUBNAME", "MARKER-PLAN-NAME",
           "MARKER-AI-MESSAGE", "MARKER-RIG")
GREY = [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]
FILL = {"frequency": 60.0, "speed": 900.0, "pulse_width": 200.0, "line_interval": 0.025, "passes": 1, "layer_type": "Scan",
        "global_passes": 1, "bidirectional": True, "cross_hatch": False, "scan_angle": 0.0, "angle_increment": 0.0}
PICTURE = {"speed": 128.0, "frequency": 60.0, "pulse_width": 300.0, "line_interval": 0.0169, "passes": 1, "global_passes": 1}


def _t(n: int) -> str:
    return f"2026-09-{1 + n // 24:02d}T{n % 24:02d}:00:00+00:00"


class World:
    def __init__(self, store: Store, files: Path):
        self.store, self.files, self.n = store, files, 0
        files.mkdir(parents=True, exist_ok=True)

    # -- records ---------------------------------------------------------------------------------------------------------------
    def file(self, name: str, data: bytes) -> str:
        path = self.files / f"MARKER-PATH-{name}"
        path.write_bytes(data)
        return str(path)

    def picture_file(self, name: str, width_mm: float, clean: dict | None = None, vectors=()) -> str:
        picture = np.tile(np.linspace(0, 255, 64), (32, 1)).astype(np.uint8)
        data = pl.export_picture(picture, width_mm, {"power": 30, "min_power": 5, **PICTURE}, name, clean=clean, vectors=list(vectors))
        return self.file(f"{name}.lbrn2", data)

    def pair(self, *, device: int, lens: int | None, material: int | None, engraving: str, path: str, check: dict | None = None,
             plan: int | None = None, status: str = "Accepted", batch: str | None = "MARKER-BATCH-17", data: dict | None = None) -> int:
        self.n += 1
        context = {"batch": batch, "note": "MARKER-NOTE", "material_id": material}
        if material is not None:
            row = self.store.one("SELECT * FROM material_profile WHERE id=?", (material,))
            context.update(titanium_name=row["name"], titanium_grade=row["grade"])
        stored = dict(data or {})
        if check is not None:
            stored["check"] = check
        return self.store.execute(
            "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,plan_id,engraving_id,engraving_title,lightburn_name,lightburn_path,"
            "photo_name,photo_path,context_json,data_json,hardware_json,created_at,accepted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (status, device, lens, self.stand, material, plan, engraving, f"MARKER-TITLE {self.n}", f"MARKER-LBNAME-{self.n}.lbrn2", path,
             f"MARKER-PHOTO-{self.n}.DNG", str(self.files / f"MARKER-PATH-photo-{self.n}.DNG"), json.dumps(context), json.dumps(stored),
             json.dumps({"serial": "MARKER-SERIAL-7781"}), _t(self.n), _t(self.n) if status == "Accepted" else None)).lastrowid

    def observe(self, pair_id: int, index: int, lab, *, power: float | None = None, chart: bool = True, role: str = "test feature",
                params: dict | None = None, name: str | None = None, rephoto: bool = False, eligible: bool | None = None,
                evidence: dict | None = None, task: str | None = None) -> int:
        row = self.store.one("SELECT * FROM pair WHERE id=?", (pair_id,))
        p = {**FILL, **({"power": power} if power is not None else {}), **(params or {})}
        p.setdefault("source_settings", {"subname": {"Value": "MARKER-SUBNAME"}, "dotWidth": {"Value": "0.05"}})
        ev = {"role": role, "layer_name": name or f"C{index:02d}", "lightburn_file": row["lightburn_name"],
              "discrepancies": ["MARKER-DISCREPANCY"],
              "color_measurement": {"mode": "reference_chart_corrected" if chart else "raw_camera_relative"}, **(evidence or {})}
        if task is not None:
            ev["task"] = {"kind": task, "basis": "explicit", "source": "operator"}
        model = int(chart if eligible is None else eligible)
        return self.store.execute(
            "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
            "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at,task_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (pair_id, index, row["device_id"], row["lens_id"], row["engraving_id"], json.dumps([float(v) for v in lab]), json.dumps(p),
             "element anchors", json.dumps({"note": "MARKER-NOTE"}), model, 0 if rephoto else 1, "MARKER-REASON", json.dumps(ev),
             row["created_at"], task)).lastrowid


def tonal_layer(index: int, bins, *, power_range=(5.0, 30.0), dither: str = "grayscale", evidence: str = "clear", adjustments=None,
                ramp: bool = False, power: float = 30.0, dot_width: float | None = None, **settings) -> dict:
    s = {**PICTURE, **settings}
    out = []
    for g, lab in zip(GREY, bins):
        step = {"gray": g, "L": lab[0], "a": lab[1], "b": lab[2], "n": 400}
        if dither == "grayscale":
            step["power_pct"] = power_range[0] + (power_range[1] - power_range[0]) * (1 - g)
        out.append(step)
    image = {"dither": dither, "dpi": 1503}
    if dot_width is not None:
        image.update(dot_correction=True, dot_width_mm=dot_width)
    tonal = {"evidence": evidence, "bins": out, "adjustments": adjustments or {}, "rho": -0.97, "samples": 3600,
             "power_range": list(power_range) if dither == "grayscale" else None}
    if ramp:
        tonal.update(measured_by="grey ramp", steps=len(out))
    return {"index": index, "name": f"C{index:02d}", "type": "Image", "power": power, "frequency_khz": s["frequency"], "speed": s["speed"],
            "pulse_width": s["pulse_width"], "line_interval": s["line_interval"], "passes": s["passes"], "global_passes": s["global_passes"],
            "image": image, "tonal": tonal, "measured_lab": list(bins[len(bins) // 2]), "source_settings": {"subname": {"Value": "MARKER-SUBNAME"}}}


def ramp_bins(dark, light, shift=(0.0, 0.0, 0.0)):
    dark, light = np.asarray(dark, float), np.asarray(light, float)
    return [[float(v) + s for v, s in zip(dark + (light - dark) * g, shift)] for g in GREY]


def build(store: Store, files: Path) -> dict:
    """The workshop: two lasers, four titanium records (two of one grade), plates, a vector work, re-photographs, chart-corrected and
    camera-relative photographs, a cleaning layer found again from a file, tonal grayscale and dot profiles, a grey ramp, a provisional
    check, a deleted pair, a matrix cell and a text recipe. Returns the ids the tests use."""
    w = World(store, files)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    store.execute("UPDATE laser_device SET name=?, serial=?, description=? WHERE id=?",
                  ("MARKER-LASER-NAME", "MARKER-SERIAL-7781", "MARKER-LASER-DESCRIPTION", laser["id"]))
    lens = lenses.create_lens(store, "MARKER-LENS-NAME", 174, 170)
    store.execute("UPDATE lens SET note=? WHERE id=?", ("MARKER-LENS-NOTE", lens["id"]))
    lenses.install(store, laser["id"], lens["id"])
    other = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    w.stand = su.save_capture_setup(store, "MARKER-RIG", "cam", "LED", "90", "ColorChecker Classic")["id"]
    m1 = su.save_material(store, "MARKER-MATERIAL-NAME A", grade="Grade 2", batch="MARKER-BATCH-17", surface="MARKER-SURFACE")["id"]
    m2 = su.save_material(store, "MARKER-MATERIAL-NAME B", grade="grade 2")["id"]
    m5 = su.save_material(store, "MARKER-MATERIAL-NAME C", grade="Grade 5", thickness_mm=0.8)["id"]
    m0 = su.save_material(store, "MARKER-MATERIAL-NAME D")["id"]               # no grade: only itself
    store.execute("INSERT INTO research_session(device_id, lens_id, material_id, goal, target, model, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", (laser["id"], lens["id"], m1, "MARKER-AI-MESSAGE", "x", "m", _t(0), _t(0)))
    plate = store.execute("INSERT INTO plan(name, mode, status, device_id, lens_id, data_json, created_at) VALUES (?,?,?,?,?,?,?)",
                          ("MARKER-PLAN-NAME", pl.MODE_PLATE, "Exported", laser["id"], lens["id"], "{}", _t(0))).lastrowid
    old = store.execute("INSERT INTO plan(name, mode, status, device_id, lens_id, data_json, created_at) VALUES (?,?,?,?,?,?,?)",
                        ("MARKER-PLAN-NAME old", pl.MODE_PLATE, "Superseded", laser["id"], lens["id"], "{}", _t(0))).lastrowid
    work = store.execute("INSERT INTO plan(name, mode, status, device_id, lens_id, data_json, created_at) VALUES (?,?,?,?,?,?,?)",
                         ("MARKER-PLAN-NAME work", pl.MODE_VECTOR, "Draft", laser["id"], lens["id"], "{}", _t(0))).lastrowid
    a, l1 = laser["id"], lens["id"]
    def bars(width: float) -> list[dict]:          # filled layers C01..C03 whose rows are ``width`` mm long
        return [{"index": i, "name": f"MARKER-SUBNAME bar {i}", "parameters": {"power": 10 * i, "frequency": 60, "speed": 900,
                 "pulse_width": 200, "line_interval": 0.025, "passes": 1},
                 "shapes": [[[(0.0, 8.0 * i), (width, 8.0 * i), (width, 8.0 * i + 5), (0.0, 8.0 * i + 5)]]]} for i in (1, 2, 3)]
    narrow, wide = w.picture_file("narrow", 20.0, vectors=bars(20.0)), w.picture_file("wide", 40.0, vectors=bars(40.0))
    wider = w.picture_file("wider", 80.0, vectors=bars(80.0))
    clean = pl.clean_layer(devices.brief(store, a)["passport"])
    letters = [{"index": 2 + i, "name": f"MARKER-SUBNAME {i}", "parameters": {"power": 20 + 5 * i, "frequency": 60, "speed": 900,
                "pulse_width": 200, "line_interval": 0.025, "passes": 1},
                "shapes": [[[(2 + 6 * k, 2), (5 + 6 * k, 2), (5 + 6 * k, 6), (2 + 6 * k, 6)]] for k in range(2)]} for i in range(2)]
    cleaned = w.picture_file("cleaned", 30.0, clean=clean, vectors=letters)

    # a plate on Grade 2 sheet A, chart-corrected, with its cleaning witness; a re-photograph; an independent engraving on sheet B
    p1 = w.pair(device=a, lens=l1, material=m1, engraving="eng-plate-1", path=narrow, plan=plate)
    w.observe(p1, -1, [70.0, 0.5, 3.0], role="pre-test cleaning witness", name="clean")
    for i, (power, lab) in enumerate(((10, [60.0, 5.0, 20.0]), (20, [45.0, 12.0, -20.0]), (30, [38.0, 20.0, -35.0])), start=1):
        w.observe(p1, i, lab, power=power)
    p2 = w.pair(device=a, lens=l1, material=m1, engraving="eng-plate-1", path=narrow, plan=plate)
    w.observe(p2, -1, [69.0, 0.4, 3.2], role="pre-test cleaning witness", name="clean")
    for i, (power, lab) in enumerate(((10, [61.0, 5.5, 19.0]), (20, [44.0, 12.5, -21.0]), (30, [38.5, 19.0, -34.0])), start=1):
        w.observe(p2, i, lab, power=power, rephoto=True)
    p3 = w.pair(device=a, lens=l1, material=m2, engraving="eng-plate-2", path=wide, plan=old)
    w.observe(p3, -1, [66.0, 0.2, 2.0], chart=False, role="pre-test cleaning witness", name="clean")
    for i, (power, lab) in enumerate(((10, [57.0, 6.0, 18.0]), (20, [43.0, 11.0, -18.0])), start=1):
        w.observe(p3, i, lab, power=power, chart=False)
    w.observe(p3, 3, [50.0, 30.0, 10.0], power=25, chart=False, evidence={"matrix_cell": {"row": 1, "col": 2}})
    # a third engraving of the 10 % recipe, far off: the recipe's engravings disagree
    p4 = w.pair(device=a, lens=l1, material=m1, engraving="eng-plate-3", path=narrow, plan=plate)
    w.observe(p4, -1, [70.2, 0.6, 2.9], role="pre-test cleaning witness", name="clean")
    w.observe(p4, 1, [52.0, 25.0, 30.0], power=10)
    w.observe(p4, 2, [40.0, 2.0, -2.0], power=12, task="text", params={"layer_type": "Scan"})
    w.observe(p4, 3, [41.0, 1.0, -1.0], power=12, params={"layer_type": "Line"})
    # a finished work accepted before its cleaning layer was recognised: camera-relative, no witness row; the file says which layer cleans
    p5 = w.pair(device=a, lens=l1, material=m1, engraving="eng-work-1", path=cleaned, plan=None)
    w.observe(p5, 0, [64.0, 0.1, 2.5], chart=False, params={"power": clean["power"]})
    w.observe(p5, 2, [48.0, 9.0, -14.0], power=20, chart=False)
    w.observe(p5, 3, [36.0, 18.0, -30.0], power=25, chart=False)
    # a vector work's engraving, as photographed (no chart, no witness)
    p6 = w.pair(device=a, lens=l1, material=m1, engraving="eng-work-2", path=wide, plan=work)
    w.observe(p6, 1, [55.0, 8.0, 10.0], power=15, chart=False)

    # tonal grayscale profiles: two engravings at 40 mm (one re-photographed), one at 20 mm, one weak, one grey ramp at 80 mm
    dark, light = [32.0, 18.0, -30.0], [66.0, 1.0, 6.0]
    p7 = w.pair(device=a, lens=l1, material=m1, engraving="eng-tone-1", path=wide,
                check={"color_measurement": {"mode": "reference_chart_corrected"}, "layers": [tonal_layer(0, ramp_bins(dark, light))]})
    w.observe(p7, 0, ramp_bins(dark, light)[4], power=30, params={"layer_type": "Image"})
    p8 = w.pair(device=a, lens=l1, material=m1, engraving="eng-tone-1", path=wide,
                check={"color_measurement": {"mode": "reference_chart_corrected"},
                       "layers": [tonal_layer(0, ramp_bins(dark, light, (1.5, -0.5, 1.0)))]})
    w.observe(p8, 0, ramp_bins(dark, light, (1.5, -0.5, 1.0))[4], power=30, params={"layer_type": "Image"}, rephoto=True)
    p9 = w.pair(device=a, lens=l1, material=m2, engraving="eng-tone-2", path=wide,
                check={"color_measurement": {"mode": "reference_chart_corrected"},
                       "layers": [tonal_layer(0, ramp_bins(dark, light, (-2.0, 1.0, -1.5)), adjustments={"Gamma": 0.8})]})
    w.observe(p9, 0, ramp_bins(dark, light, (-2.0, 1.0, -1.5))[4], power=30, params={"layer_type": "Image"})
    p10 = w.pair(device=a, lens=l1, material=m1, engraving="eng-tone-3", path=narrow,
                 check={"color_measurement": {"mode": "reference_chart_corrected"}, "layers": [tonal_layer(0, ramp_bins(dark, light, (4.0, 2.0, 2.0)))]})
    w.observe(p10, 0, ramp_bins(dark, light, (4.0, 2.0, 2.0))[4], power=30, params={"layer_type": "Image"})
    w.pair(device=a, lens=l1, material=m1, engraving="eng-tone-4", path=narrow,
           check={"color_measurement": {"mode": "reference_chart_corrected"}, "layers": [tonal_layer(0, ramp_bins(dark, light), evidence="weak")]})
    p12 = w.pair(device=a, lens=l1, material=m1, engraving="eng-ramp-1", path=wider,
                 check={"color_measurement": {"mode": "raw_camera_relative"},
                        "layers": [tonal_layer(0, ramp_bins(dark, light, (-1.0, 0.0, 0.0)), ramp=True)]})
    w.observe(p12, -1, [65.0, 0.3, 2.2], chart=False, role="pre-test cleaning witness", name="clean")
    # a dot kind: power and dot width belong to the mode; one profile lies over vector fills
    p13 = w.pair(device=a, lens=l1, material=m1, engraving="eng-dots-1", path=wide,
                 check={"color_measurement": {"mode": "reference_chart_corrected"},
                        "layers": [tonal_layer(0, ramp_bins([40.0, 10.0, -20.0], [68.0, 0.5, 4.0]), dither="jarvis", power=45.0, dot_width=0.05)]})
    w.observe(p13, 0, [52.0, 5.0, -8.0], power=45, params={"layer_type": "Image"})
    w.pair(device=a, lens=l1, material=m1, engraving="eng-dots-2", path=wide,
           check={"color_measurement": {"mode": "reference_chart_corrected"}, "composition": {"picture_over_fills": True},
                  "layers": [tonal_layer(0, ramp_bins([40.0, 10.0, -20.0], [68.0, 0.5, 4.0]), dither="jarvis", power=45.0, dot_width=0.05)]})

    # the other laser (no lens) on Grade 5, a record with no grade, a provisional check and a deleted pair
    p15 = w.pair(device=other["id"], lens=None, material=m5, engraving="eng-other-1", path=narrow)
    w.observe(p15, 1, [58.0, 4.0, 12.0], power=10)
    w.observe(p15, 2, [47.0, 10.0, -12.0], power=20)
    p16 = w.pair(device=a, lens=l1, material=m0, engraving="eng-nograde-1", path=narrow)
    w.observe(p16, 1, [59.0, 4.5, 15.0], power=10)
    w.pair(device=a, lens=l1, material=m1, engraving="eng-pending", path=narrow, status="Ready to accept",
           check={"color_measurement": {"mode": "reference_chart_corrected"}, "alignment": {"valid": True},
                  "layers": [{"index": 1, "name": "C01", "type": "Scan", "measured_lab": [50.0, 0.0, 0.0], "power": 40, "frequency_khz": 60,
                              "speed": 900, "pulse_width": 200, "line_interval": 0.025, "passes": 1}]})
    gone = w.pair(device=a, lens=l1, material=m1, engraving="eng-deleted", path=narrow)
    w.observe(gone, 1, [10.0, 0.0, 0.0], power=99)
    store.execute("UPDATE pair SET status='Deleted' WHERE id=?", (gone,))
    return {"laser": a, "lens": l1, "other": other["id"], "m1": m1, "m2": m2, "m5": m5, "m0": m0, "plate": plate, "work": work,
            "pairs": {"p1": p1, "p5": p5, "p7": p7, "p8": p8, "p13": p13}}


def bulk(store: Store, files: Path, measurements: int, per_capture: int = 10) -> dict:
    """A workshop of ``measurements`` area-fill measurements on one laser, lens and titanium, ``per_capture`` layers per photograph, written
    in one transaction: the size a release of it is measured at (``tools/bench_tcelab.py``, the constant-memory test)."""
    w = World(store, files)
    laser = devices.create_from_template(store, "jpt-ydflp-e-60-m7-m-r")
    lens = lenses.create_lens(store, "Bench lens", 174, 170)
    lenses.install(store, laser["id"], lens["id"])
    stand = su.save_capture_setup(store, "Bench rig", "cam", "LED", "90", "ColorChecker Classic")["id"]
    material = su.save_material(store, "Bench sheet", grade="Grade 2")["id"]
    bars = [{"index": i, "name": f"bar {i}", "parameters": {"power": i, "frequency": 60, "speed": 900, "pulse_width": 200, "line_interval": 0.025,
             "passes": 1}, "shapes": [[[(0.0, 4.0 * i), (30.0, 4.0 * i), (30.0, 4.0 * i + 3), (0.0, 4.0 * i + 3)]]]} for i in range(1, per_capture + 1)]
    path = w.picture_file("bench", 30.0, vectors=bars)
    pairs = (measurements + per_capture - 1) // per_capture
    context = json.dumps({"material_id": material, "titanium_name": "Bench sheet", "titanium_grade": "Grade 2"})
    with store.transaction():
        for n in range(pairs):
            pair = store.execute(
                "INSERT INTO pair(status,device_id,lens_id,stand_id,material_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,"
                "context_json,data_json,created_at,accepted_at) VALUES ('Accepted',?,?,?,?,?,?,?,?,?,?,'{}',?,?)",
                (laser["id"], lens["id"], stand, material, f"eng-{n}", "bench.lbrn2", path, f"bench-{n}.DNG", str(files / f"bench-{n}.DNG"),
                 context, _t(0), _t(0))).lastrowid
            rows = []
            for i in range(1, min(per_capture, measurements - n * per_capture) + 1):
                power = 1.0 + (n * per_capture + i) % 90
                lab = [70.0 - power / 3, (power % 17) - 8.0, (power % 23) - 11.0]
                rows.append((pair, i, laser["id"], lens["id"], f"eng-{n}", json.dumps(lab), json.dumps({**FILL, "power": power}), "markers",
                             "{}", 1, 1, "bench", json.dumps({"role": "test feature", "layer_name": f"C{i:02d}",
                                                              "color_measurement": {"mode": "reference_chart_corrected"}}), _t(0)))
            store.conn.executemany(
                "INSERT INTO observation(pair_id,layer_index,device_id,lens_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
                "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return {"laser": laser["id"], "lens": lens["id"], "material": material, "pairs": pairs}
