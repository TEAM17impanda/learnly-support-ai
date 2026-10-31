"""Дії AI. Єдине місце, що змінює стан учня. Кожна дія має check() (policy-guard) і run().

LLM лише пропонує дію; чи можна її виконати — вирішує check(), незалежно від промпту.
"""
from dataclasses import dataclass
from typing import Callable

from .context import build_context
from .data import COHORTS
from .policy import (MAX_EXTENSION_DAYS, MAX_EXTENSIONS, MAX_MENTOR_SESSIONS,
                     REFUND_WINDOW_DAYS)


class PolicyError(Exception):
    """Дію заборонено політикою школи."""


def _need(cond: bool, msg: str):
    if not cond:
        raise PolicyError(msg)


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---------- extend_deadline ----------
def _chk_extend(s, a):
    days = _int(a.get("days"), 5)
    _need(not s["refunded"], "Курс уже повернено")
    _need(1 <= days <= MAX_EXTENSION_DAYS, f"Продовження: від 1 до {MAX_EXTENSION_DAYS} днів")
    _need(s["extensions_used"] < MAX_EXTENSIONS,
          f"Ліміт продовжень вичерпано ({MAX_EXTENSIONS})")


def _run_extend(s, a):
    days = _int(a.get("days"), 5)
    s["extensions_used"] += 1
    s["deadline_extra_days"] += days
    return {"summary": f"Дедлайн продовжено на {days} дн. "
                       f"(використано {s['extensions_used']}/{MAX_EXTENSIONS})"}


# ---------- transfer_cohort ----------
def _chk_transfer(s, a):
    ctx = build_context(s)
    target = a.get("target_cohort") or ctx["next_cohort"]
    _need(not s["refunded"], "Курс уже повернено")
    _need(not s["transferred"], "Перенос уже використано (дозволено один раз)")
    _need(ctx["progress_total"] <= 0.5, "Перенос можливий лише до 50% прогресу")
    cohort = next((c for c in COHORTS if c["id"] == target), None)
    _need(cohort is not None, f"Потоку {target} не існує")
    _need(cohort["course"] == s["course"], "Потік належить іншому курсу")
    _need(cohort["id"] != s["cohort"], "Учень уже в цьому потоці")


def _run_transfer(s, a):
    target = a.get("target_cohort") or build_context(s)["next_cohort"]
    old = s["cohort"]
    s["cohort"] = target
    s["transferred"] = True
    s["lessons_expected"] = 0  # новий потік починається з нуля, відставання знімається
    return {"summary": f"Учня перенесено з потоку {old} на {target}"}


# ---------- request_refund ----------
def _chk_refund(s, a):
    ctx = build_context(s)
    _need(not s["refunded"], "Кошти вже повернуто")
    _need(ctx["has_paid"], "Немає успішної оплати")
    _need(ctx["days_since_payment"] <= REFUND_WINDOW_DAYS,
          f"З оплати минуло {ctx['days_since_payment']} дн. — вікно повернення "
          f"{REFUND_WINDOW_DAYS} дн. закрите")


def _run_refund(s, a):
    ctx = build_context(s)
    amount = round(ctx["amount_paid"] * ctx["refund_pct"] / 100)
    first = next(p for p in s["payments"] if p["status"] == "paid")
    first["status"] = "refunded"
    s["refunded"] = True
    s["access_active"] = False
    return {"amount": amount, "summary": f"Повернення {amount} грн ({ctx['refund_pct']}%) оформлено"}


# ---------- refund_duplicate_charge ----------
def _chk_dup(s, a):
    _need(bool(build_context(s)["duplicate_ids"]), "Дубльованих списань не знайдено")


def _run_dup(s, a):
    ctx = build_context(s)
    for p in s["payments"]:
        if p["id"] in ctx["duplicate_ids"]:
            p["status"] = "refunded"
    amt = ctx["duplicate_amount"]
    return {"amount": amt, "summary": f"Повернено дубльоване списання: {amt} грн"}


# ---------- grant_access ----------
def _chk_access(s, a):
    ctx = build_context(s)
    _need(not s["refunded"], "Курс повернено — доступ не надається")
    _need(ctx["has_paid"], "Немає успішної оплати")
    _need(not s["access_active"], "Доступ уже активний")


def _run_access(s, a):
    s["access_active"] = True
    return {"summary": "Доступ до курсу відновлено"}


# ---------- book_mentor_session ----------
def _chk_mentor(s, a):
    _need(not s["refunded"], "Курс повернено")
    _need(s["mentor_sessions"] < MAX_MENTOR_SESSIONS,
          f"Ліміт ментор-сесій ({MAX_MENTOR_SESSIONS}) вичерпано")


def _run_mentor(s, a):
    s["mentor_sessions"] += 1
    return {"summary": "Безкоштовну ментор-сесію заброньовано"}


# ---------- issue_certificate ----------
def _chk_cert(s, a):
    _need(s["lessons_done"] >= s["lessons_total"],
          f"Пройдено {s['lessons_done']}/{s['lessons_total']} уроків")
    _need(not s["certificate_issued"], "Сертифікат уже видано")
    _need(not s["refunded"], "Курс повернено")


def _run_cert(s, a):
    s["certificate_issued"] = True
    return {"summary": "Сертифікат видано та надіслано на email"}


# ---------- escalate_to_human ----------
TEAMS = {"billing", "tech", "curator"}


def _chk_escalate(s, a):
    team = a.get("team", "curator")
    _need(isinstance(team, str) and team in TEAMS, f"Невідома команда: {team}")


def _run_escalate(s, a):
    team, reason = a.get("team", "curator"), a.get("reason", "потрібна людина")
    s["escalations"].append({"team": team, "reason": reason})
    return {"summary": f"Передано команді «{team}»: {reason}"}


@dataclass
class Tool:
    name: str
    risk: str  # low | medium | high
    title: str
    description: str
    check: Callable
    run: Callable
    args_hint: str = ""

    @property
    def requires_approval(self) -> bool:
        return self.risk in ("medium", "high")


TOOLS = {t.name: t for t in [
    Tool("extend_deadline", "low", "Продовжити дедлайн",
         "Продовжує дедлайн здачі завдань", _chk_extend, _run_extend, "days: int 1-7"),
    Tool("transfer_cohort", "medium", "Перенести на наступний потік",
         "Переносить учня на наступний потік того ж курсу", _chk_transfer, _run_transfer,
         "target_cohort: str (id потоку)"),
    Tool("request_refund", "high", "Оформити повернення коштів",
         "Повертає кошти за курс у межах вікна повернення", _chk_refund, _run_refund, ""),
    Tool("refund_duplicate_charge", "high", "Повернути дубльоване списання",
         "Повертає зайве (дубльоване) списання", _chk_dup, _run_dup, ""),
    Tool("grant_access", "low", "Відновити доступ до курсу",
         "Активує доступ, якщо оплата є", _chk_access, _run_access, ""),
    Tool("book_mentor_session", "low", "Забронювати ментор-сесію",
         "Безкоштовна 1:1 сесія з ментором", _chk_mentor, _run_mentor, ""),
    Tool("issue_certificate", "low", "Видати сертифікат",
         "Видає сертифікат, якщо пройдено всі уроки", _chk_cert, _run_cert, ""),
    Tool("escalate_to_human", "medium", "Передати людині",
         "Ескалація команді billing|tech|curator", _chk_escalate, _run_escalate,
         "team: billing|tech|curator, reason: str"),
]}


def tool_catalog() -> list[dict]:
    return [{"name": t.name, "risk": t.risk, "description": t.description, "args": t.args_hint}
            for t in TOOLS.values()]


def check(student: dict, tool: str, args: dict) -> None:
    """Кидає PolicyError, якщо дію виконувати не можна."""
    if tool not in TOOLS:
        raise PolicyError(f"Невідома дія: {tool}")
    TOOLS[tool].check(student, args or {})


def execute(student: dict, tool: str, args: dict) -> dict:
    check(student, tool, args)
    result = TOOLS[tool].run(student, args or {})
    result["tool"] = tool
    return result
