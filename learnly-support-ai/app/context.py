"""Похідний контекст учня: факти, на які спирається AI і tools."""
from datetime import date

from .data import COHORTS, COURSES
from .policy import (FULL_REFUND_MAX_PROGRESS, MAX_EXTENSIONS, REFUND_WINDOW_DAYS,
                     TRANSFER_MAX_PROGRESS)


def next_cohort_id(student: dict):
    today = date.today()
    for c in COHORTS:
        if (c["course"] == student["course"] and c["id"] != student["cohort"]
                and date.fromisoformat(c["start"]) > today):
            return c["id"]
    return None


def build_context(s: dict) -> dict:
    today = date.today()
    paid = [p for p in s["payments"] if p["status"] == "paid"]
    first_paid = min((date.fromisoformat(p["date"]) for p in paid), default=None)
    days = (today - first_paid).days if first_paid else None

    groups: dict = {}
    for p in paid:
        groups.setdefault((p["amount"], p["date"]), []).append(p)
    dup_ids, dup_amount = [], 0
    for (amount, _), items in groups.items():
        if len(items) > 1:
            for extra in items[1:]:
                dup_ids.append(extra["id"])
                dup_amount += amount

    total, done, exp = s["lessons_total"], s["lessons_done"], s["lessons_expected"]
    progress_total = done / total if total else 0.0
    pace_ratio = done / exp if exp else 1.0
    course = COURSES[s["course"]]
    nxt = next_cohort_id(s)

    return {
        "student_id": s["id"],
        "course_name": course["name"],
        "cohort": s["cohort"],
        "amount_paid": paid[0]["amount"] if paid else 0,
        "has_paid": bool(paid),
        "days_since_payment": days,
        "lessons_total": total, "lessons_done": done, "lessons_expected": exp,
        "lessons_left": total - done,
        "gap": max(exp - done, 0),
        "progress_total": round(progress_total, 2),
        "pace_ratio": round(pace_ratio, 2),
        "last_login_days_ago": s["last_login_days_ago"],
        "access_active": s["access_active"],
        "refunded": s["refunded"],
        "past_tickets": s["past_tickets"],
        "extensions_used": s["extensions_used"],
        "duplicate_ids": dup_ids, "duplicate_amount": dup_amount,
        "refund_eligible": (not s["refunded"] and days is not None and days <= REFUND_WINDOW_DAYS),
        "refund_pct": 100 if progress_total <= FULL_REFUND_MAX_PROGRESS else 50,
        "can_extend": (not s["refunded"] and s["extensions_used"] < MAX_EXTENSIONS),
        "can_transfer": (not s["refunded"] and not s["transferred"]
                         and progress_total <= TRANSFER_MAX_PROGRESS and nxt is not None),
        "next_cohort": nxt,
        "certificate_ready": done >= total and not s["certificate_issued"],
        "certificate_issued": s["certificate_issued"],
    }
