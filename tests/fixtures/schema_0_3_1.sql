-- The database schema of release 0.3.1 (src/titanium_platform/db.py before DEC-063), with the columns its
-- start-up migration added. Used to build an older database for the migration tests.
CREATE TABLE IF NOT EXISTS laser_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family TEXT NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    axes_json TEXT NOT NULL,
    pulse_width REAL NOT NULL,
    line_interval REAL NOT NULL,
    passes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (family, version)
);
CREATE TABLE IF NOT EXISTS lens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    focal_length_mm REAL NOT NULL,
    field_mm REAL,
    expansion REAL NOT NULL DEFAULT 1,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS laser_device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    manufacturer TEXT,
    model TEXT,
    serial TEXT,
    description TEXT,
    data_json TEXT NOT NULL,
    lens_id INTEGER REFERENCES lens(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS device_document (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS material_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    family TEXT NOT NULL,
    batch TEXT,
    grade TEXT,
    thickness_mm REAL,
    surface TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_setup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    camera TEXT NOT NULL,
    lighting TEXT NOT NULL,
    angle TEXT NOT NULL,
    reference_chart TEXT NOT NULL,
    raw_format INTEGER NOT NULL DEFAULT 1,
    chart_detection_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL UNIQUE,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    speed REAL NOT NULL,
    geometry_json TEXT NOT NULL,
    cells_json TEXT NOT NULL,
    proposal_id INTEGER,
    lens_json TEXT,
    material_id INTEGER REFERENCES material_profile(id),
    test_type TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    plate_id INTEGER REFERENCES plate(id),
    markers INTEGER NOT NULL DEFAULT 0,
    plan_identifier TEXT,
    band_count INTEGER,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pair (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    stand_id INTEGER REFERENCES capture_setup(id),
    material_id INTEGER REFERENCES material_profile(id),
    plate_id INTEGER REFERENCES plate(id),
    plan_id INTEGER REFERENCES plan(id),
    engraving_id TEXT NOT NULL,
    engraving_title TEXT,
    lightburn_name TEXT NOT NULL,
    lightburn_path TEXT NOT NULL,
    photo_name TEXT NOT NULL,
    photo_path TEXT NOT NULL,
    context_json TEXT NOT NULL,
    data_json TEXT NOT NULL,
    hardware_json TEXT,
    created_at TEXT NOT NULL,
    accepted_at TEXT
);
CREATE TABLE IF NOT EXISTS observation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL REFERENCES pair(id),
    layer_index INTEGER NOT NULL,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    engraving_id TEXT NOT NULL,
    lab_json TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    alignment_method TEXT NOT NULL,
    context_json TEXT NOT NULL,
    model_eligible INTEGER NOT NULL,
    repeat_eligible INTEGER NOT NULL,
    eligibility_reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS observation_no_update BEFORE UPDATE ON observation
BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS observation_no_delete BEFORE DELETE ON observation
BEGIN SELECT RAISE(ABORT, 'observations are immutable'); END;
CREATE TABLE IF NOT EXISTS capability_finding (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id INTEGER NOT NULL REFERENCES pair(id),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL,
    parameters_json TEXT,
    evidence_json TEXT NOT NULL,
    next_test TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(pair_id, purpose)
);
CREATE TABLE IF NOT EXISTS research_session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL REFERENCES laser_device(id),
    lens_id INTEGER NOT NULL REFERENCES lens(id),
    material_id INTEGER NOT NULL REFERENCES material_profile(id),
    goal TEXT NOT NULL,
    target TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES research_session(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_trace_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_memory (
    session_id INTEGER PRIMARY KEY REFERENCES research_session(id),
    through_message_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_insight (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES research_session(id),
    purpose TEXT NOT NULL,
    claim TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_pair_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS research_message_session_idx ON research_message(session_id,id);
CREATE INDEX IF NOT EXISTS research_insight_session_idx ON research_insight(session_id,id);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    parameters_key TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    stage TEXT NOT NULL,
    questioned INTEGER NOT NULL DEFAULT 0,
    doubt_json TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (profile_id, parameters_key)
);
CREATE TABLE IF NOT EXISTS knowledge_event (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_id INTEGER NOT NULL REFERENCES knowledge(id),
    at TEXT NOT NULL,
    type TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    reason TEXT NOT NULL,
    observation_ids_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_color (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    lab_json TEXT NOT NULL,
    source_plan_id INTEGER NOT NULL,
    source_color_key TEXT NOT NULL,
    proposal_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (source_plan_id, source_color_key)
);
CREATE TABLE IF NOT EXISTS proposal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES laser_profile(id),
    base_signature TEXT NOT NULL,
    seed INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    explanation TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (profile_id, base_signature, seed)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
ALTER TABLE laser_profile ADD COLUMN device_id INTEGER REFERENCES laser_device(id);
ALTER TABLE laser_profile ADD COLUMN lens_id INTEGER REFERENCES lens(id);
ALTER TABLE plan ADD COLUMN research_session_id INTEGER REFERENCES research_session(id);
