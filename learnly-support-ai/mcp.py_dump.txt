"""MCP-шлюз: єдиний шлях агента до даних школи.

Агент НЕ звертається до БД напряму. Він викликає інструменти з білого списку, а шлюз:
  - пускає лише дозволені операції для ролі того, хто викликає (agent — читання, admin — запис);
  - віддає лише дозволені поля (пароль, телефон, повний номер картки не виходять за межі шлюзу);
  - не дає «вивантажити таблицю»: пошук вимагає хоча б один фільтр і обмежений лімітом;
  - пише кожен виклик в audit log разом із тікетом/розмовою, у межах якої його зробили.

У продакшні цей шар — окремий MCP-сервер; тут — той самий контракт у процесі застосунку.
"""
from dataclasses import dataclass
from typing import Callable

from .store import STATE


class MCPDenied(Exception):
    """Виклик заборонено політикою доступу шлюзу."""


@dataclass
class MCPTool:
    name: str
    description: str
    access: str            # read | write
    callers: tuple         # хто може викликати
    table: str
    fields: tuple          # поля, які шлюз віддає назовні
    fn: Callable


ACCOUNT_FIELDS = ("id", "name", "email", "role", "lessons_balance", "children_count")
PAYMENT_FIELDS = ("id", "amount", "package", "payer_email", "card_last4", "status", "paid_at", "linked_account")
CHILD_FIELDS = ("name", "grade", "course")
HIDDEN_FIELDS = ("password_hash", "phone", "card_number")  # ніколи не виходять зі шлюзу
MAX_ROWS = 5


def _pick(row: dict, fields: tuple) -> dict:
    return {f: row.get(f) for f in fields}


def _account(account_id: str) -> dict:
    acc = STATE.school["accounts"].get(account_id)
    if not acc:
        raise MCPDenied(f"Акаунт {account_id} не знайдено")
    return acc


def _get_account(account_id: str) -> dict:
    acc = _account(account_id)
    return _pick({**acc, "children_count": len(acc["children"])}, ACCOUNT_FIELDS)


def _get_children(account_id: str) -> list:
    return [_pick(c, CHILD_FIELDS) for c in _account(account_id)["children"]]


def _find_payments(email: str | None = None, card_last4: str | None = None,
                   amount: int | None = None) -> list:
    if not (email or card_last4 or amount):
        raise MCPDenied("Пошук платежів без фільтра заборонено (захист від вивантаження таблиці)")
    rows = [p for p in STATE.school["payments"]
            if (not email or p["payer_email"].lower() == email.lower())
            and (not card_last4 or p["card_last4"] == card_last4)
            and (not amount or p["amount"] == amount)]
    return [_pick(p, PAYMENT_FIELDS) for p in rows[:MAX_ROWS]]


def _link_payment(payment_id: str, account_id: str) -> dict:
    acc = _account(account_id)
    pay = next((p for p in STATE.school["payments"] if p["id"] == payment_id), None)
    if not pay:
        raise MCPDenied(f"Платіж {payment_id} не знайдено")
    if pay["linked_account"]:
        raise MCPDenied(f"Платіж {payment_id} уже прив'язано до {pay['linked_account']}")
    pay["linked_account"] = account_id
    acc["lessons_balance"] += pay["lessons"]
    return {"payment_id": payment_id, "account_id": account_id, "lessons_added": pay["lessons"],
            "lessons_balance": acc["lessons_balance"]}


TOOLS = {t.name: t for t in [
    MCPTool("get_account", "Профіль акаунта: пошта, роль, баланс занять, к-сть дітей", "read",
            ("agent", "admin"), "accounts", ACCOUNT_FIELDS, _get_account),
    MCPTool("get_children", "Діти, прив'язані до сімейного акаунта", "read",
            ("agent", "admin"), "accounts.children", CHILD_FIELDS, _get_children),
    MCPTool("find_payments", "Пошук платежів за поштою / останніми 4 цифрами картки / сумою", "read",
            ("agent", "admin"), "payments", PAYMENT_FIELDS, _find_payments),
    MCPTool("link_payment", "Прив'язати платіж до акаунта і зарахувати заняття (фінансова операція)", "write",
            ("admin",), "payments, accounts", ("payment_id", "account_id", "lessons_added"), _link_payment),
]}


def _summary(result) -> str:
    if isinstance(result, list):
        return f"{len(result)} запис(ів)"
    if isinstance(result, dict) and "lessons_added" in result:
        return f"+{result['lessons_added']} занять"
    return "ok"


def call(tool: str, caller: str, ref: str | None = None, **args) -> dict:
    """Виклик інструмента через шлюз. Повертає запис трасування {tool, args, ok, result, summary}."""
    entry = {"tool": tool, "caller": caller, "args": args}
    try:
        t = TOOLS.get(tool)
        if not t:
            raise MCPDenied(f"Інструмента {tool} немає в білому списку")
        if caller not in t.callers:
            raise MCPDenied(f"Роль «{caller}» не має доступу до «{tool}» ({t.access})")
        result = t.fn(**args)
        entry.update(ok=True, result=result, summary=_summary(result))
    except MCPDenied as e:
        entry.update(ok=False, result=None, summary=f"⛔ {e}")
    except TypeError:
        entry.update(ok=False, result=None, summary="⛔ Недозволені аргументи")
    STATE.log("mcp_call", tool=tool, caller=caller, ref=ref, ok=entry["ok"], summary=entry["summary"])
    return entry


def catalog() -> list[dict]:
    return [{"name": t.name, "description": t.description, "access": t.access, "callers": list(t.callers),
             "table": t.table, "fields": list(t.fields)} for t in TOOLS.values()] + \
           [{"hidden_fields": list(HIDDEN_FIELDS), "max_rows": MAX_ROWS}]
