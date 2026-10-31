"""SQLite-сховище: учні, тікети, ескалації, audit log, налаштування.

Файл бази — DB_PATH (за замовчуванням data/learnly.db); ":memory:" — для тестів.
Записи зберігаємо як JSON-документи + ключові поля в окремих колонках для запитів і індексів.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "learnly.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id         TEXT PRIMARY KEY,
    student_id TEXT NOT NULL REFERENCES students(id),
    status     TEXT NOT NULL,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE TABLE IF NOT EXISTS escalations (
    id          TEXT PRIMARY KEY,
    source_role TEXT NOT NULL,
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL,
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status, priority);
CREATE TABLE IF NOT EXISTS audit (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts    TEXT NOT NULL,
    event TEXT NOT NULL,
    data  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Database:
    def __init__(self, path: str | None = None):
        path = path or os.getenv("DB_PATH") or str(DEFAULT_PATH)
        if path != ":memory:":
            # відносний шлях — від кореня проєкту, а не від папки, звідки запустили сервер
            p = Path(path)
            path = str(p if p.is_absolute() else DEFAULT_PATH.parent.parent / p)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0

    def load(self) -> dict:
        q = lambda sql: [json.loads(r[0]) for r in self.conn.execute(sql)]  # noqa: E731
        kv = {k: json.loads(v) for k, v in self.conn.execute("SELECT key, value FROM kv")}
        audit = [{"ts": ts, "event": ev, **json.loads(d)}
                 for ts, ev, d in self.conn.execute("SELECT ts, event, data FROM audit ORDER BY id")]
        return {
            "students": q("SELECT data FROM students ORDER BY rowid"),
            "tickets": q("SELECT data FROM tickets ORDER BY rowid"),
            "escalations": q("SELECT data FROM escalations ORDER BY rowid"),
            "audit": audit, "kv": kv,
        }

    def save(self, students: dict, tickets: dict, escalations: list, new_audit: list,
             kv: dict, wipe_audit: bool = False):
        """Повний знімок стану однією транзакцією (обсяг даних демо — десятки записів)."""
        with self._lock, self.conn:
            for table in ("tickets", "escalations", "students", "kv"):
                self.conn.execute(f"DELETE FROM {table}")
            if wipe_audit:
                self.conn.execute("DELETE FROM audit")
            self.conn.executemany("INSERT INTO students VALUES (?, ?, ?)",
                                  [(s["id"], s["name"], _dump(s)) for s in students.values()])
            self.conn.executemany("INSERT INTO tickets VALUES (?, ?, ?, ?)",
                                  [(t["id"], t["student_id"], t["status"], _dump(t))
                                   for t in tickets.values()])
            self.conn.executemany("INSERT INTO escalations VALUES (?, ?, ?, ?, ?)",
                                  [(e["id"], e["source_role"], e["status"], e["priority"], _dump(e))
                                   for e in escalations])
            self.conn.executemany(
                "INSERT INTO audit (ts, event, data) VALUES (?, ?, ?)",
                [(a["ts"], a["event"], _dump({k: v for k, v in a.items() if k not in ("ts", "event")}))
                 for a in new_audit])
            self.conn.executemany("INSERT INTO kv VALUES (?, ?)", [(k, _dump(v)) for k, v in kv.items()])
