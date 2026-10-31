"""In-memory стан демо: учні, тікети, audit log, налаштування."""
import copy
import itertools
import os
from datetime import datetime

from .data import (DEMO_MESSAGES, HISTORY, INITIAL_CALENDAR, INITIAL_ESCALATIONS,
                   ROLE_PRESETS, fresh_students)  # noqa: F401


class State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.students = fresh_students()
        self.tickets: dict[str, dict] = {}
        self.audit: list[dict] = []
        self.settings = {"autonomy": os.getenv("AUTONOMY", "copilot")}
        self.escalations = copy.deepcopy(INITIAL_ESCALATIONS)
        self.calendar = copy.deepcopy(INITIAL_CALENDAR)
        self._ticket_seq = itertools.count(1001)
        self._action_seq = itertools.count(1)
        self._esc_seq = itertools.count(103)

    def new_ticket_id(self) -> str:
        return f"T-{next(self._ticket_seq)}"

    def new_action_id(self) -> str:
        return f"A-{next(self._action_seq)}"

    def new_esc_id(self) -> str:
        return f"ESC-{next(self._esc_seq)}"

    def log(self, event: str, **data):
        self.audit.append({"ts": now(), "event": event, **data})


def now() -> str:
    return datetime.now().strftime("%H:%M:%S")


STATE = State()
