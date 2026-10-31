"""Стан демо: учні, тікети, ескалації, audit log, налаштування. Працює в пам'яті, зберігається в SQLite."""
import copy
import os
from datetime import datetime

from .data import (DEMO_MESSAGES, HISTORY, INITIAL_CALENDAR, INITIAL_ESCALATIONS,
                   ROLE_PRESETS, fresh_students)  # noqa: F401
from .db import Database


class State:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        self.reset()

    def reset(self):
        self.students = fresh_students()
        self.tickets: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.settings = {"autonomy": os.getenv("AUTONOMY", "copilot")}
        self.escalations = copy.deepcopy(INITIAL_ESCALATIONS)
        self.calendar = copy.deepcopy(INITIAL_CALENDAR)
        self.seq = {"ticket": 1001, "action": 1, "esc": 103}
        self._audit_saved = 0
        self._wipe_audit = True  # після reset старий журнал у БД замінюється

    # ---------- персистентність ----------
    def load(self) -> bool:
        """Піднімає стан із БД. False — база порожня (потрібен seed)."""
        if self.db.is_empty():
            return False
        d = self.db.load()
        self.students = {s["id"]: s for s in d["students"]}
        self.tickets = {t["id"]: t for t in d["tickets"]}
        self.escalations = d["escalations"]
        self.audit = d["audit"]
        self.settings = d["kv"].get("settings", self.settings)
        self.calendar = d["kv"].get("calendar", self.calendar)
        self.seq = d["kv"].get("seq", self.seq)
        self._audit_saved, self._wipe_audit = len(self.audit), False
        return True

    def save(self):
        self.db.save(self.students, self.tickets, self.escalations, self.audit[self._audit_saved:],
                     {"settings": self.settings, "calendar": self.calendar, "seq": self.seq},
                     wipe_audit=self._wipe_audit)
        self._audit_saved, self._wipe_audit = len(self.audit), False

    # ---------- ідентифікатори ----------
    def _next(self, kind: str) -> int:
        value = self.seq[kind]
        self.seq[kind] += 1
        return value

    def new_ticket_id(self) -> str:
        return f"T-{self._next('ticket')}"

    def new_action_id(self) -> str:
        return f"A-{self._next('action')}"

    def new_esc_id(self) -> str:
        return f"ESC-{self._next('esc')}"

    def log(self, event: str, **data):
        self.audit.append({"ts": now(), "event": event, **data})


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


STATE = State()
