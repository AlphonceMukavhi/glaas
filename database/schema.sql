-- GLAAS Database Schema
-- Gamified Learning Assessment Alignment System
-- Grade 7 Science

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('researcher','teacher')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    full_name TEXT,
    gender TEXT DEFAULT 'Unspecified',
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS curriculum_objectives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_number INTEGER NOT NULL,
    assessment_type TEXT NOT NULL CHECK(assessment_type IN ('prior_exercise','quizizz','formal_exam')),
    curriculum_objective_id INTEGER NOT NULL REFERENCES curriculum_objectives(id) ON DELETE RESTRICT,
    max_marks INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(item_number, assessment_type)
);

CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    assessment_item_id INTEGER NOT NULL REFERENCES assessment_items(id) ON DELETE CASCADE,
    assessment_type TEXT NOT NULL,
    curriculum_objective_id INTEGER NOT NULL,
    marks_obtained REAL NOT NULL DEFAULT 0,
    max_marks REAL NOT NULL DEFAULT 1,
    percentage REAL GENERATED ALWAYS AS (CASE WHEN max_marks > 0 THEN (marks_obtained / max_marks) * 100.0 ELSE 0 END) STORED,
    entered_by INTEGER REFERENCES users(id),
    entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(learner_id, assessment_item_id)
);

CREATE TABLE IF NOT EXISTS questionnaire_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    respondent_role TEXT NOT NULL CHECK(respondent_role IN ('teacher','principal')),
    q1_useful INTEGER, q2_curriculum INTEGER, q3_mastery INTEGER,
    q4_clearer INTEGER, q5_recommend INTEGER,
    q6_easy_nav INTEGER, q7_easy_read INTEGER, q8_independent INTEGER,
    q9_quiz_aligned INTEGER, q10_quiz_effective INTEGER,
    q11_open TEXT, q12_open TEXT, q13_open TEXT, q14_open TEXT,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS csv_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    assessment_type TEXT,
    rows_imported INTEGER DEFAULT 0,
    imported_by INTEGER REFERENCES users(id),
    imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'success',
    errors TEXT
);

-- Default system settings
INSERT OR IGNORE INTO system_settings VALUES ('school_name', 'Primary School');
INSERT OR IGNORE INTO system_settings VALUES ('researcher_name', 'Alphonce Mukavhi');
INSERT OR IGNORE INTO system_settings VALUES ('academic_year', '2025');
INSERT OR IGNORE INTO system_settings VALUES ('study_title', 'Enhancing Students'' STEM Performance Outcomes through Gamification');
INSERT OR IGNORE INTO system_settings VALUES ('grade', 'Grade 7');
INSERT OR IGNORE INTO system_settings VALUES ('subject', 'Science');
