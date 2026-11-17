"""SQLite database for SupervisorMatch (full-stack version).

Mirrors the roadmap's 8-table schema (PostgreSQL version) in SQLite so the
project runs on any laptop with zero database setup:
users, supervisor_profiles, student_profiles, project_ideas, matches,
requests, feedback, notifications.
"""

import csv
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if os.environ.get("VERCEL") == "1":
    # Vercel's filesystem is read-only except /tmp: keep the runtime
    # database there. It is recreated and reseeded on every cold start.
    DB_PATH = Path("/tmp") / "supervisormatch.db"
else:
    DB_PATH = BASE_DIR / "supervisormatch.db"
DATA_CSV = ROOT_DIR / "data.csv"

ADMIN_EMAIL = "admin@sbbusba.edu.pk"
ADMIN_PASSWORD = "admin123"
DEFAULT_TEACHER_PASSWORD = "teacher123"

# One-click demo student for the exhibition (judges try the student flow).
DEMO_STUDENT_EMAIL = "demo@student.sbbusba.edu.pk"
DEMO_STUDENT_PASSWORD = "demo123"
DEMO_STUDENT_NAME = "Zafarullah Shah"
DEMO_STUDENT_ROLL = "24BS(IT)128"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables (safe to call on every startup)."""
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'supervisor', 'admin')),
            department TEXT,
            campus TEXT DEFAULT 'Main Campus',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS supervisor_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE REFERENCES users(id),
            designation TEXT,
            qualification TEXT,
            research_interests TEXT,
            capacity INTEGER DEFAULT 5,
            current_load INTEGER DEFAULT 0,
            bio TEXT,
            record_type TEXT DEFAULT 'Real',
            email_status TEXT
        );
        CREATE TABLE IF NOT EXISTS student_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE REFERENCES users(id),
            roll_no TEXT,
            semester TEXT,
            cgpa REAL
        );
        CREATE TABLE IF NOT EXISTS project_ideas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER REFERENCES users(id),
            title TEXT,
            description TEXT,
            domain TEXT,
            keywords TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER REFERENCES project_ideas(id),
            supervisor_id INTEGER REFERENCES users(id),
            score REAL,
            rank INTEGER,
            explanation TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idea_id INTEGER REFERENCES project_ideas(id),
            student_id INTEGER REFERENCES users(id),
            supervisor_id INTEGER REFERENCES users(id),
            message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER REFERENCES users(id),
            supervisor_id INTEGER REFERENCES users(id),
            idea_id INTEGER REFERENCES project_ideas(id),
            rating INTEGER,
            comment TEXT
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            message TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()


def _row_to_dict(row):
    return dict(row) if row is not None else None


def get_user_by_email(email):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def create_user(name, email, password_hash, role, department=None, campus="Main Campus"):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (name, email, password_hash, role, department, campus)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, password_hash, role, department, campus),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id


def seed():
    """Seed the admin account, the demo student and the 100 supervisors
    from data.csv.

    Runs only for missing rows, so it is safe on every startup.
    """
    try:
        from backend.auth import hash_password
    except ImportError:
        from auth import hash_password  # running from inside backend/

    init_db()
    # Single connection for the whole seed: SQLite allows only one writer,
    # so no second connection may write while this one is open.
    conn = get_conn()
    cur = conn.cursor()
    if cur.execute("SELECT id FROM users WHERE email = ?", (ADMIN_EMAIL,)).fetchone() is None:
        cur.execute(
            "INSERT INTO users (name, email, password_hash, role, department)"
            " VALUES (?, ?, ?, 'admin', 'Administration')",
            ("Admin", ADMIN_EMAIL, hash_password(ADMIN_PASSWORD)),
        )
        print(f"Seeded admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")

    # Demo student (exhibition one-click login as a student).
    demo = cur.execute(
        "SELECT id FROM users WHERE email = ?", (DEMO_STUDENT_EMAIL,)
    ).fetchone()
    if demo is None:
        cur.execute(
            "INSERT INTO users (name, email, password_hash, role, department)"
            " VALUES (?, ?, ?, 'student', 'Information Technology')",
            (DEMO_STUDENT_NAME, DEMO_STUDENT_EMAIL, hash_password(DEMO_STUDENT_PASSWORD)),
        )
        demo_id = cur.lastrowid
        cur.execute(
            "INSERT INTO student_profiles (user_id, roll_no, semester)"
            " VALUES (?, ?, '6th Semester')",
            (demo_id, DEMO_STUDENT_ROLL),
        )
        print(f"Seeded demo student: {DEMO_STUDENT_EMAIL} / {DEMO_STUDENT_PASSWORD}")

    if not DATA_CSV.exists():
        print(f"Warning: {DATA_CSV} not found, supervisor seeding skipped.")
        conn.commit()
        conn.close()
        return
    existing = {r[0] for r in cur.execute("SELECT email FROM users").fetchall()}
    added = 0
    with open(DATA_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            email = (row.get("Email") or "").strip()
            if not email or email in existing:
                continue
            cur.execute(
                "INSERT INTO users (name, email, password_hash, role, department, campus)"
                " VALUES (?, ?, ?, 'supervisor', ?, ?)",
                (
                    (row.get("Name") or "").strip(),
                    email,
                    hash_password(DEFAULT_TEACHER_PASSWORD),
                    (row.get("Department") or "").strip(),
                    (row.get("Campus") or "Main Campus").strip(),
                ),
            )
            user_id = cur.lastrowid
            cur.execute(
                "INSERT INTO supervisor_profiles"
                " (user_id, designation, qualification, research_interests,"
                "  capacity, current_load, record_type, email_status)"
                " VALUES (?, ?, ?, ?, 5, 0, ?, ?)",
                (
                    user_id,
                    (row.get("Designation") or "").strip(),
                    (row.get("Qualification") or "").strip(),
                    (row.get("Research_Interests") or "").strip(),
                    (row.get("Record_Type") or "Real").strip(),
                    (row.get("Email_Status") or "").strip(),
                ),
            )
            existing.add(email)
            added += 1
    conn.commit()
    conn.close()
    if added:
        print(f"Seeded {added} supervisors from data.csv "
              f"(default password: {DEFAULT_TEACHER_PASSWORD})")


def reset_demo():
    """Exhibition helper: wipe every demo record and re-seed from scratch
    (admin + demo student + 100 supervisors). Admin-only, via
    POST /admin/reset-demo. Lets a judge try the full approval cycle
    again from a clean slate."""
    conn = get_conn()
    cur = conn.cursor()
    for table in (
        "feedback", "notifications", "requests", "matches",
        "project_ideas", "student_profiles", "supervisor_profiles", "users",
    ):
        cur.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()
    seed()


def get_supervisors(search=None, department=None):
    """Active supervisors with their profiles, for matching and directory."""
    conn = get_conn()
    query = (
        "SELECT u.id AS user_id, u.name, u.email, u.department, u.campus,"
        " p.designation, p.qualification, p.research_interests, p.capacity,"
        " p.current_load, p.bio, p.record_type, p.email_status,"
        " (SELECT AVG(rating) FROM feedback WHERE supervisor_id = u.id) AS avg_rating,"
        " (SELECT COUNT(*) FROM feedback WHERE supervisor_id = u.id) AS feedback_count,"
        " (SELECT COUNT(*) FROM matches WHERE supervisor_id = u.id) AS total_matches,"
        " (SELECT COUNT(*) FROM requests WHERE supervisor_id = u.id"
        "  AND status = 'approved') AS assignments"
        " FROM users u JOIN supervisor_profiles p ON p.user_id = u.id"
        " WHERE u.role = 'supervisor' AND u.is_active = 1"
    )
    params = []
    if department and department != "All":
        query += " AND u.department = ?"
        params.append(department)
    if search:
        query += " AND (u.name LIKE ? OR p.research_interests LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def notify(user_id, message):
    conn = get_conn()
    conn.execute(
        "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
        (user_id, message),
    )
    conn.commit()
    conn.close()
