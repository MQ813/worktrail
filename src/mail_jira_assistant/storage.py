"""SQLite migrations. All application state lives on one local host."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, message_id TEXT, conversation TEXT, subject TEXT, sender TEXT, recipients TEXT, date TEXT, body TEXT, raw_path TEXT, attachments TEXT);
CREATE TABLE IF NOT EXISTS inquiries(id TEXT PRIMARY KEY REFERENCES sources(id), state TEXT NOT NULL DEFAULT 'needs_review');
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id), kind TEXT, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, token TEXT, lease REAL, error TEXT, input_version INTEGER DEFAULT 0, available REAL DEFAULT 0, request_id TEXT DEFAULT '', UNIQUE(source_id,kind,input_version,request_id));
CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, job_id INTEGER, token TEXT, input TEXT, output TEXT, error TEXT, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS classifications(source_id TEXT PRIMARY KEY, result TEXT);
CREATE TABLE IF NOT EXISTS drafts(source_id TEXT PRIMARY KEY, generated TEXT, body TEXT, version INTEGER DEFAULT 1, review TEXT DEFAULT 'generated');
CREATE TABLE IF NOT EXISTS edits(id INTEGER PRIMARY KEY, source_id TEXT, version INTEGER, body TEXT, review TEXT);
CREATE TABLE IF NOT EXISTS sync_errors(path TEXT PRIMARY KEY, error TEXT);
CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY, inquiry_id TEXT REFERENCES inquiries(id), source_id TEXT REFERENCES sources(id), fingerprint TEXT, snapshot TEXT, created REAL, UNIQUE(inquiry_id,fingerprint));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, inquiry_id TEXT, revision_id INTEGER, kind TEXT, detail TEXT, UNIQUE(revision_id,kind));
CREATE TABLE IF NOT EXISTS classification_history(id INTEGER PRIMARY KEY, inquiry_id TEXT, revision_id INTEGER, result TEXT, created REAL);
CREATE TABLE IF NOT EXISTS manual_classifications(id INTEGER PRIMARY KEY, inquiry_id TEXT, revision_id INTEGER, result TEXT, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS overrides(id INTEGER PRIMARY KEY, inquiry_id TEXT, revision_id INTEGER, state TEXT, note TEXT, created REAL);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, inquiry_id TEXT, description TEXT, assignee TEXT, due_at TEXT, state TEXT DEFAULT 'proposed', evidence TEXT, version INTEGER DEFAULT 1, UNIQUE(inquiry_id,description,assignee));
CREATE TABLE IF NOT EXISTS draft_versions(id INTEGER PRIMARY KEY, inquiry_id TEXT, revision_id INTEGER, generated TEXT, created REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, kind TEXT, target TEXT, detail TEXT, created REAL);
CREATE TABLE IF NOT EXISTS cursors(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, hash TEXT);
CREATE TABLE IF NOT EXISTS jira_issues(id TEXT PRIMARY KEY, server_id TEXT, issue_key TEXT, url TEXT, state TEXT DEFAULT 'active', error TEXT, snapshot TEXT, next_poll REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS locks(name TEXT PRIMARY KEY, token TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _column(db, table, name, definition):
    if name not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def connect(runtime):
    path = Path(runtime)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path / "app.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    ready = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migrations'"
    ).fetchone()
    if ready and db.execute("SELECT max(version) FROM migrations").fetchone()[0] == 5:
        return db
    if ready:
        # A consistent pre-upgrade snapshot also retains edits in an older database.
        previous = db.execute("SELECT max(version) FROM migrations").fetchone()[0] or 0
        if previous > 5:
            db.close()
            raise ValueError("database_schema_newer_than_application")
        backup_path = path / ("pre-migration-v" + str(previous) + ".sqlite3")
        if not backup_path.exists():
            snapshot = sqlite3.connect(backup_path)
            try:
                db.backup(snapshot)
            finally:
                snapshot.close()
    db.execute("BEGIN IMMEDIATE")

    def script(sql):
        for statement in sql.split(";"):
            if statement.strip():
                db.execute(statement)

    script(SCHEMA)
    # Upgrade original P1 database without deleting user edits or attempts.
    if "input_version" not in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}:
        script("""ALTER TABLE jobs RENAME TO jobs_v1;
        CREATE TABLE jobs(id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id), kind TEXT, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, token TEXT, lease REAL, error TEXT, input_version INTEGER DEFAULT 0, available REAL DEFAULT 0, request_id TEXT DEFAULT '', UNIQUE(source_id,kind,input_version,request_id));
        INSERT INTO jobs(id,source_id,kind,state,attempts,token,lease,error) SELECT id,source_id,kind,state,attempts,token,lease,error FROM jobs_v1;
        DROP TABLE jobs_v1;""")
    if "request_id" not in {r[1] for r in db.execute("PRAGMA table_info(jobs)")}:
        script("""ALTER TABLE jobs RENAME TO jobs_v2;
        CREATE TABLE jobs(id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id), kind TEXT, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, token TEXT, lease REAL, error TEXT, input_version INTEGER DEFAULT 0, available REAL DEFAULT 0, request_id TEXT DEFAULT '', UNIQUE(source_id,kind,input_version,request_id));
        INSERT INTO jobs(id,source_id,kind,state,attempts,token,lease,error,input_version,available) SELECT id,source_id,kind,state,attempts,token,lease,error,input_version,available FROM jobs_v2;
        DROP TABLE jobs_v2;""")
    _column(db, "attempts", "runner_log", "TEXT")
    _column(db, "attempts", "prompt_version", "TEXT DEFAULT '2'")
    for name, definition in [
        ("inquiry_id", "TEXT"),
        ("direction", "TEXT DEFAULT 'unknown'"),
        ("kind", "TEXT DEFAULT 'mail'"),
        ("baseline", "INTEGER DEFAULT 1"),
        ("coverage", "TEXT DEFAULT 'complete'"),
    ]:
        _column(db, "sources", name, definition)
    for name, definition in [
        ("revision_id", "INTEGER DEFAULT 0"),
        ("freshness", "TEXT DEFAULT 'current'"),
        ("context_hash", "TEXT"),
    ]:
        _column(db, "drafts", name, definition)
    db.execute("UPDATE sources SET inquiry_id=id WHERE inquiry_id IS NULL")
    import hashlib
    import json
    import time

    for old in db.execute(
        "SELECT * FROM sources WHERE NOT EXISTS(SELECT 1 FROM revisions WHERE revisions.source_id=sources.id)"
    ).fetchall():
        snapshot = json.dumps(
            {
                "body": old["body"],
                "subject": old["subject"],
                "attachments": json.loads(old["attachments"] or "[]"),
                "migrated": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        rev = db.execute(
            "INSERT INTO revisions(inquiry_id,source_id,fingerprint,snapshot,created) VALUES(?,?,?,?,?)",
            (
                old["inquiry_id"],
                old["id"],
                hashlib.sha256(snapshot.encode()).hexdigest(),
                snapshot,
                time.time(),
            ),
        ).lastrowid
        db.execute(
            "UPDATE drafts SET revision_id=? WHERE source_id=? AND revision_id=0",
            (rev, old["id"]),
        )
    db.execute("INSERT OR IGNORE INTO migrations VALUES(1)")
    db.execute("INSERT OR IGNORE INTO migrations VALUES(2)")
    db.execute("INSERT OR IGNORE INTO migrations VALUES(3)")
    db.execute("CREATE INDEX IF NOT EXISTS sources_message ON sources(message_id)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS sources_conversation ON sources(conversation)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS sources_inquiry ON sources(inquiry_id)")
    db.execute(
        "CREATE INDEX IF NOT EXISTS revisions_inquiry ON revisions(inquiry_id,id)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(state,available,id)")
    db.execute("INSERT OR IGNORE INTO migrations VALUES(4)")
    script("""
    CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS inquiry_projects(inquiry_id TEXT PRIMARY KEY REFERENCES inquiries(id), project_id INTEGER REFERENCES projects(id));
    CREATE TABLE IF NOT EXISTS activities(id INTEGER PRIMARY KEY, inquiry_id TEXT REFERENCES inquiries(id), project_id INTEGER REFERENCES projects(id), action_id INTEGER REFERENCES actions(id), description TEXT NOT NULL, performed_on TEXT, source_date TEXT, collected_at REAL, status TEXT NOT NULL DEFAULT 'needs_review', origin_key TEXT UNIQUE, version INTEGER NOT NULL DEFAULT 1, duplicate_of INTEGER REFERENCES activities(id), minutes INTEGER);
    CREATE TABLE IF NOT EXISTS activity_evidence(activity_id INTEGER REFERENCES activities(id), source_id TEXT REFERENCES sources(id), revision_id INTEGER REFERENCES revisions(id), detail TEXT, UNIQUE(activity_id,source_id,revision_id));
    CREATE TABLE IF NOT EXISTS activity_edits(id INTEGER PRIMARY KEY, activity_id INTEGER REFERENCES activities(id), snapshot TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS worklog_imports(path TEXT PRIMARY KEY, hash TEXT NOT NULL, imported REAL NOT NULL);
    """)
    db.execute("INSERT OR IGNORE INTO migrations VALUES(5)")
    db.commit()
    return db
