"""DEC-063: a database written before 0.4.0 is migrated once from laser profiles to laser + lens, keeping every value."""
import json
import sqlite3
from pathlib import Path

import pytest

from titanium_platform import devices, knowledge as kn, lenses, model
from titanium_platform import setup as su
from titanium_platform.db import MigrationError, Store

OLD_SCHEMA = (Path(__file__).parent / "fixtures" / "schema_0_3_1.sql").read_text(encoding="utf-8")
T = "2026-10-01T10:00:00+00:00"
REBUILT = ("plate", "plan", "pair", "observation", "knowledge", "target_color", "proposal")


def old_database(folder: Path, schema: str = OLD_SCHEMA) -> sqlite3.Connection:
    """An empty database exactly as release 0.3.1 left it (WAL mode, the profile columns)."""
    folder.mkdir(parents=True)
    conn = sqlite3.connect(folder / "titanium.sqlite")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(schema)
    return conn


def profile(conn, pid, device_id, lens_id, name=None):
    conn.execute("INSERT INTO laser_profile(id,family,version,name,axes_json,pulse_width,line_interval,passes,created_at,device_id,lens_id) "
                 "VALUES (?,?,1,?,'[]',1,0.05,1,?,?,?)", (pid, f"f{pid}", name or f"P{pid}", T, device_id, lens_id))


def populated(folder: Path) -> sqlite3.Connection:
    """Two lasers: laser 1 with lens 1 installed (profiles 1 and 3), laser 2 without a lens (profile 2). Pair 3 remembers
    lens 2 in its own hardware snapshot although its profile names lens 1. Laser 3 and lens 3 have only an unused profile
    (0.3.1 created one on every capability-plate preview)."""
    conn = old_database(folder)
    conn.execute("INSERT INTO lens(id,name,focal_length_mm,field_mm,expansion,created_at) VALUES (1,'F-Theta',174,170,1,?)", (T,))
    conn.execute("INSERT INTO lens(id,name,focal_length_mm,field_mm,expansion,created_at) VALUES (2,'Spare',254,NULL,1,?)", (T,))
    conn.execute("INSERT INTO lens(id,name,focal_length_mm,field_mm,expansion,created_at) VALUES (3,'Unused',160,NULL,1,?)", (T,))
    for did, lens in ((1, 1), (2, None), (3, 3)):
        conn.execute("INSERT INTO laser_device(id,name,data_json,lens_id,created_at,updated_at) VALUES (?,?,'{}',?,?,?)", (did, f"L{did}", lens, T, T))
    profile(conn, 1, 1, 1)
    profile(conn, 2, 2, None)
    profile(conn, 3, 1, 1)
    profile(conn, 4, 3, 3, "L3 · Unused")
    conn.execute("INSERT INTO material_profile(id,name,family,created_at) VALUES (1,'Grade 2','Titanium',?)", (T,))
    conn.execute("INSERT INTO capture_setup(id,name,camera,lighting,angle,reference_chart,created_at) VALUES (1,'Rig','c','l','90','x',?)", (T,))
    snapshot = json.dumps({"id": 1, "name": "F-Theta", "focal_length_mm": 174.0, "field_mm": 170.0, "expansion": 1.0,
                           "spot_diameter_um": None, "taken_at": T})
    conn.execute("INSERT INTO plate(id,experiment_id,profile_id,speed,geometry_json,cells_json,lens_json,material_id,created_at) "
                 "VALUES (1,'TCE-1',1,900,'{}','[]',?,1,?)", (snapshot, T))
    for plan_id in (1, 2):
        conn.execute("INSERT INTO plan(id,name,mode,status,profile_id,plate_id,markers,plan_identifier,data_json,created_at) "
                     "VALUES (?,'Plate','Calibration plate','Exported',1,?,1,'TCE-1','{\"layers\": []}',?)", (plan_id, 1 if plan_id == 1 else None, T))
    conn.execute("DELETE FROM plan WHERE id=2")                      # its id must never be given out again
    pairs = ((1, 1, 1, 1, '{"device": {"id": 1}}'), (2, 2, None, None, '{"device": {"id": 2}, "lens": null}'),
             (3, 3, None, None, '{"device": {"id": 1}, "lens": {"id": 2, "name": "Spare"}}'))
    for pair_id, pid, plate_id, plan_id, hardware in pairs:
        conn.execute("INSERT INTO pair(id,status,profile_id,stand_id,material_id,plate_id,plan_id,engraving_id,engraving_title,lightburn_name,"
                     "lightburn_path,photo_name,photo_path,context_json,data_json,hardware_json,created_at,accepted_at) "
                     "VALUES (?,'Accepted',?,1,1,?,?,?,'work','a.lbrn2','/x','p.raw','/y','{\"material_id\": 1}','{}',?,?,?)",
                     (pair_id, pid, plate_id, plan_id, f"e{pair_id}", hardware, T, T))
    for oid, pair_id, pid in ((1, 1, 1), (2, 1, 1), (3, 2, 2), (4, 3, 3)):
        conn.execute("INSERT INTO observation(id,pair_id,layer_index,profile_id,engraving_id,lab_json,parameters_json,alignment_method,context_json,"
                     "model_eligible,repeat_eligible,eligibility_reason,evidence_json,created_at) VALUES (?,?,?,?,?,?,?,'markers',?,1,1,'ok',?,?)",
                     (oid, pair_id, oid, pid, f"e{pair_id}", f"[50.12345678901234, {oid}.5, -3.25]",
                      json.dumps({"power": 10 * oid, "frequency": 40, "speed": 900, "pulse_width": 200, "line_interval": 0.025,
                                  "passes": 1, "profile_id": pid}),
                      '{"material_id": 1}', json.dumps({"layer_name": f"C{oid}", "pixels": 1234}), T))
    conn.execute("INSERT INTO knowledge(id,profile_id,parameters_key,parameters_json,stage,updated_at) VALUES (1,1,'k','{}','validated',?)", (T,))
    conn.execute("INSERT INTO knowledge(id,profile_id,parameters_key,parameters_json,stage,updated_at) VALUES (2,2,'k','{}','measured',?)", (T,))
    conn.execute("INSERT INTO knowledge_event(knowledge_id,at,type,from_stage,to_stage,reason,observation_ids_json) VALUES (1,?,'created',NULL,'measured','x','[1]')", (T,))
    conn.execute("INSERT INTO target_color(profile_id,lab_json,source_plan_id,source_color_key,created_at) VALUES (1,'[60, 5, 5]',1,'c0',?)", (T,))
    conn.execute("INSERT INTO proposal(profile_id,base_signature,seed,data_json,created_at) VALUES (2,'sig',1729,'{\"parameters\": []}',?)", (T,))
    rules = {"repeat_threshold": 3, "delta_tolerance": 4.0, "variance_threshold": 2.0, "criteria_agreed": True}
    conn.execute("INSERT INTO setting VALUES ('rules:1', ?)", (json.dumps(rules),))
    conn.execute("INSERT INTO setting VALUES ('rules:3', ?)", (json.dumps({**rules, "repeat_threshold": 5}),))   # 0.3.1 applied profile 1's
    conn.execute("INSERT INTO setting VALUES ('rules:2', ?)", (json.dumps({**rules, "delta_tolerance": 9.0}),))
    conn.execute("INSERT INTO setting VALUES ('marker_layer', '{\"power\": 20}')")
    conn.commit()
    return conn


def rows(conn, table):
    return {r["id"]: dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")}


def test_an_older_database_is_migrated_once_with_every_value_kept(tmp_path):
    data = tmp_path / "data"
    conn = populated(data)
    before = {t: rows(conn, t) for t in REBUILT}
    conn.close()

    store = Store(data)
    for table in REBUILT:
        after = rows(store.conn, table)
        assert after.keys() == before[table].keys()
        for rid, old in before[table].items():
            new = after[rid]
            pid = old.pop("profile_id")
            assert new.pop("legacy_profile_id") == pid
            device_lens = (new.pop("device_id"), new.pop("lens_id"))
            own_lens = (table, rid) in (("pair", 3), ("observation", 4))     # pair 3 remembers lens 2 itself, observation 4 is its
            assert device_lens == ((1, 2) if own_lens else {1: (1, 1), 2: (2, None), 3: (1, 1)}[pid])
            if table == "pair":                                   # stored values are byte for byte the old ones
                assert new.pop("hardware_json") == old.pop("hardware_json")
            assert {k: v for k, v in new.items() if k in old} == old and set(old) <= set(new)
    assert store.one("SELECT lab_json FROM observation WHERE id=1")["lab_json"] == "[50.12345678901234, 1.5, -3.25]"

    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        store.execute("UPDATE observation SET lab_json='[0, 0, 0]' WHERE id=1")
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        store.execute("DELETE FROM observation WHERE id=1")
    with pytest.raises(sqlite3.DatabaseError, match="read-only archive"):
        store.execute("UPDATE laser_profile SET name='x' WHERE id=1")
    assert store.one("SELECT COUNT(*) AS n FROM laser_profile")["n"] == 4
    assert store.query("PRAGMA foreign_key_list(laser_profile)") == []            # the archive refers to nothing

    settings = {r["key"]: json.loads(r["value_json"]) for r in store.query("SELECT * FROM setting")}
    assert set(settings) == {"rules:laser:1/lens:1", "rules:laser:2/lens:unknown", "marker_layer"}
    assert su.get_rules(store, 1, 1)["delta_tolerance"] == 4.0 and su.get_rules(store, 2, None)["delta_tolerance"] == 9.0
    assert su.get_rules(store, 1, 1)["repeat_threshold"] == 3          # profiles 1 and 3 differ: the lowest id wins, as in 0.3.1

    backups = list((data / "backups").glob("titanium-before-0.4.0-*.sqlite"))
    assert len(backups) == 1
    copy = sqlite3.connect(backups[0])
    assert "profile_id" in {r[1] for r in copy.execute("PRAGMA table_info(observation)")}
    assert copy.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 4
    copy.close()

    store.execute("INSERT INTO plan(name,mode,status,device_id,lens_id,markers,data_json,created_at) VALUES ('n','m','s',1,1,0,'{}',?)", (T,))
    assert store.one("SELECT MAX(id) AS id FROM plan")["id"] == 3          # the deleted plan 2 keeps its id
    assert lenses.create_lens(store, "Unmarked lens")["focal_length_mm"] is None     # REQ-019: a lens may stay incomplete
    assert [k["id"] for k in kn.list_for_setup(store, 1, 1)] == [1] and [k["id"] for k in kn.list_for_setup(store, 2, None)] == [2]
    # profiles 1 and 3 named the same laser and lens; observation 4 follows the lens its photograph remembers
    assert set(model.knowledge_summaries(store, 1, 1)) == {f"{p}|40|900|200|0.025|1|ti:id:1" for p in (10, 20)}
    assert set(model.knowledge_summaries(store, 1, 2)) == {"40|40|900|200|0.025|1|ti:id:1"}
    detail = json.loads(store.one("SELECT detail_json FROM audit WHERE action='schema_migrated'")["detail_json"])
    assert detail["rows"]["observation"] == 4 and detail["rows"]["laser_profile"] == 4
    assert detail["lens_from_own_record"] == {"pair": [[3, 1, 2]], "observation": [[4, 1, 2]]}     # [row, profile's lens, own lens]
    assert detail["rules"] == {"rules:laser:1/lens:1": "rules:1", "rules:laser:2/lens:unknown": "rules:2"}
    assert detail["rules_discarded"] == {"rules:3": {"repeat_threshold": 5, "delta_tolerance": 4.0, "variance_threshold": 2.0,
                                                     "criteria_agreed": True}}
    migrated_rows = {t: rows(store.conn, t) for t in REBUILT}
    store.close()

    again = Store(data)                                     # the second start finds nothing to migrate
    again._migrate_from_profiles()                          # a process that started at the same moment finds nothing either
    assert len(list((data / "backups").iterdir())) == 1
    assert again.one("SELECT COUNT(*) AS n FROM audit WHERE action='schema_migrated'")["n"] == 1
    assert {t: rows(again.conn, t) for t in REBUILT} == migrated_rows
    again.close()


@pytest.mark.parametrize("damage, reason", [
    ("UPDATE laser_profile SET device_id=NULL WHERE id=2", r"name no laser: 2 \(P2\).*UPDATE laser_profile SET device_id=<laser id> WHERE id=<profile id>"),
    ("UPDATE knowledge SET profile_id=3 WHERE id=2", "would become one entry"),
    ("UPDATE pair SET profile_id=9 WHERE id=3", "does not exist"),
])
def test_a_database_it_cannot_map_is_refused_and_left_unchanged(tmp_path, damage, reason):
    data = tmp_path / "data"
    conn = populated(data)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(damage)
    conn.commit()
    dump = list(conn.iterdump())
    conn.close()
    with pytest.raises(MigrationError, match=reason):
        Store(data)
    conn = sqlite3.connect(data / "titanium.sqlite")
    assert list(conn.iterdump()) == dump
    conn.close()
    assert not (data / "backups").exists()


def test_a_new_database_has_no_profiles_and_needs_no_migration(tmp_path):
    store = Store(tmp_path / "data")
    tables = {r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "laser_profile" not in tables and not (tmp_path / "data" / "backups").exists()
    for table in REBUILT:
        columns = {r["name"] for r in store.query(f"PRAGMA table_info({table})")}
        assert {"device_id", "lens_id", "legacy_profile_id"} <= columns and "profile_id" not in columns
    store.close()


def test_an_archived_profile_never_blocks_deleting_an_unused_laser_or_lens(tmp_path):
    data = tmp_path / "data"
    populated(data).close()
    store = Store(data)
    lenses.install(store, 3, None)
    devices.delete_device(store, 3)                     # only the archived profile 4 named laser 3 and lens 3
    lenses.delete_lens(store, 3)
    assert tuple(store.one("SELECT device_id, lens_id FROM laser_profile WHERE id=4")) == (3, 3)    # the archive keeps its values
    with pytest.raises(su.ProtectedError):
        devices.delete_device(store, 1)
    store.close()


def test_a_failure_in_the_middle_of_the_rebuild_leaves_the_database_unchanged_and_a_retry_works(tmp_path, monkeypatch):
    data = tmp_path / "data"
    conn = populated(data)
    dump = list(conn.iterdump())
    conn.close()
    rebuild = Store._rebuild

    def failing(self, table, sequences):
        if table == "observation":                      # plate, plan and pair are already rebuilt by then
            raise RuntimeError("disk full")
        return rebuild(self, table, sequences)

    monkeypatch.setattr(Store, "_rebuild", failing)
    with pytest.raises(RuntimeError, match="disk full"):
        Store(data)
    conn = sqlite3.connect(data / "titanium.sqlite")
    assert list(conn.iterdump()) == dump
    conn.close()
    monkeypatch.setattr(Store, "_rebuild", rebuild)
    store = Store(data)
    assert store.one("SELECT COUNT(*) AS n FROM observation WHERE device_id IS NOT NULL")["n"] == 4
    store.close()


def test_a_database_older_than_0_3_1_without_laser_links_is_refused_with_what_to_do(tmp_path):
    data = tmp_path / "data"
    conn = old_database(data, OLD_SCHEMA.split("ALTER TABLE laser_profile", 1)[0])
    conn.execute("INSERT INTO laser_profile(id,family,version,name,axes_json,pulse_width,line_interval,passes,created_at) "
                 "VALUES (1,'f',1,'MOPA','[]',200,0.025,1,?)", (T,))
    conn.execute("INSERT INTO capture_setup(id,name,camera,lighting,angle,reference_chart,created_at) VALUES (1,'Rig','c','l','90','x',?)", (T,))
    conn.execute("INSERT INTO pair(status,profile_id,stand_id,engraving_id,lightburn_name,lightburn_path,photo_name,photo_path,context_json,"
                 "data_json,created_at) VALUES ('Accepted',1,1,'e','a.lbrn2','/x','p.raw','/y','{}','{}',?)", (T,))
    conn.commit()
    dump = list(conn.iterdump())
    conn.close()
    with pytest.raises(MigrationError, match="start version 0.3.1 once on this data directory") as refused:
        Store(data)
    assert "UPDATE laser_profile SET device_id=<laser id>" in str(refused.value)
    conn = sqlite3.connect(data / "titanium.sqlite")
    assert list(conn.iterdump()) == dump
    conn.close()


def test_a_refused_database_stops_the_programs_with_a_clean_message_and_exit_code_2(tmp_path, capsys):
    from titanium_platform import cli, mcp_server
    from titanium_platform.api.app import create_app
    data = tmp_path / "data"
    conn = populated(data)
    conn.execute("UPDATE laser_profile SET device_id=NULL WHERE id=2")
    conn.commit()
    conn.close()
    for start in (lambda: create_app(data), lambda: cli.main(["--data-dir", str(data)]),
                  lambda: mcp_server.main(["--data-dir", str(data)])):
        with pytest.raises(SystemExit) as stopped:
            start()
        assert stopped.value.code == 2
        err = capsys.readouterr().err
        assert "cannot migrate the database to 0.4.0" in err and "Traceback" not in err and err.count("\n") == 1
