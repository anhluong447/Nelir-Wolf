"""SQLite helpers: connections that are always closed, and the project schema."""
import sqlite3
from contextlib import contextmanager

SCHEMA_VERSION = 2


@contextmanager
def connect(path: str):
    """Open a connection, commit on success, roll back on error, ALWAYS close.

    `with sqlite3.connect(...)` only commits; it never closes the handle, which
    keeps the file locked on Windows. Use this helper everywhere instead.
    """
    conn = sqlite3.connect(path, timeout=30)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_project_db(path: str):
    """Create / upgrade the per-project translation database."""
    with connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS translation_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file TEXT NOT NULL,
                category TEXT NOT NULL,
                path TEXT NOT NULL,
                row_type TEXT NOT NULL,
                raw TEXT NOT NULL,
                mtl TEXT DEFAULT '',
                translated TEXT DEFAULT '',
                status INTEGER DEFAULT 0 -- 0 empty, 1 mtl, 2 reviewed, 3 qa failed
            )
        """)
        cols = _columns(conn, "translation_rows")
        if "locked" not in cols:
            conn.execute("ALTER TABLE translation_rows ADD COLUMN locked INTEGER DEFAULT 0")
        if "qa_flags" not in cols:
            conn.execute("ALTER TABLE translation_rows ADD COLUMN qa_flags TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file ON translation_rows(file)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON translation_rows(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON translation_rows(category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw ON translation_rows(raw)")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_path ON translation_rows(file, path)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS glossary (
                src TEXT PRIMARY KEY,
                dst TEXT NOT NULL,
                note TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


def status_counts(conn, file: str = None) -> dict:
    """Counts used by every stats display. Percent is over unlocked rows only.
    `file` scopes the counts to one dump file."""
    counts = {"total": 0, "empty": 0, "mtl": 0, "translated": 0, "qa": 0, "locked": 0}
    where, params = ("WHERE file = ?", (file,)) if file else ("", ())
    for status, locked, n in conn.execute(
        f"SELECT status, locked, COUNT(*) FROM translation_rows {where} GROUP BY status, locked", params
    ):
        counts["total"] += n
        if locked:
            counts["locked"] += n
            continue
        key = {0: "empty", 1: "mtl", 2: "translated", 3: "qa"}.get(status, "empty")
        counts[key] += n
    translatable = counts["total"] - counts["locked"]
    counts["translatable"] = translatable
    counts["completed"] = counts["mtl"] + counts["translated"]
    counts["percent"] = round(counts["completed"] / translatable * 100, 1) if translatable else 0.0
    return counts
