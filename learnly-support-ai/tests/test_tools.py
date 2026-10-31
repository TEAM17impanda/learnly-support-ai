"""Policy-guard: дії порушують політику → PolicyError, стан не змінюється."""
import pytest

from app import tools
from app.data import fresh_students
from app.tools import PolicyError


@pytest.fixture
def students():
    return fresh_students()


def test_refund_inside_window_full_amount(students):
    s = students["s4"]  # 2/24 уроків = 8% ≤ 30%, 12 днів
    r = tools.execute(s, "request_refund", {})
    assert r["amount"] == 9900
    assert s["refunded"] and not s["access_active"]


def test_refund_partial_when_progress_over_30_percent(students):
    s = students["s1"]  # 9/24 = 37.5% > 30%
    assert tools.execute(s, "request_refund", {})["amount"] == 4950


def test_refund_outside_window_is_blocked_and_state_unchanged(students):
    s = students["s6"]  # 30 днів
    with pytest.raises(PolicyError, match="закрите"):
        tools.execute(s, "request_refund", {})
    assert not s["refunded"] and s["access_active"]


def test_cannot_refund_twice(students):
    s = students["s4"]
    tools.execute(s, "request_refund", {})
    with pytest.raises(PolicyError):
        tools.execute(s, "request_refund", {})


def test_extension_limits(students):
    s = students["s1"]
    tools.execute(s, "extend_deadline", {"days": 5})
    tools.execute(s, "extend_deadline", {"days": 7})
    with pytest.raises(PolicyError, match="Ліміт"):
        tools.execute(s, "extend_deadline", {"days": 3})
    assert s["deadline_extra_days"] == 12


@pytest.mark.parametrize("days", [0, 8, -1])
def test_extension_days_out_of_range(students, days):
    with pytest.raises(PolicyError):
        tools.execute(students["s1"], "extend_deadline", {"days": days})


def test_transfer_once_and_only_same_course(students):
    s = students["s1"]
    r = tools.execute(s, "transfer_cohort", {"target_cohort": "PY-NOV"})
    assert s["cohort"] == "PY-NOV" and "PY-NOV" in r["summary"]
    with pytest.raises(PolicyError, match="один раз"):
        tools.execute(s, "transfer_cohort", {"target_cohort": "PY-DEC"})


def test_transfer_to_other_course_blocked(students):
    with pytest.raises(PolicyError, match="іншому курсу"):
        tools.execute(students["s1"], "transfer_cohort", {"target_cohort": "UX-DEC"})


def test_transfer_blocked_after_half_of_course(students):
    s = students["s2"]  # 20/24
    with pytest.raises(PolicyError, match="50%"):
        tools.execute(s, "transfer_cohort", {"target_cohort": "UX-DEC"})


def test_duplicate_charge_refund(students):
    s = students["s3"]
    r = tools.execute(s, "refund_duplicate_charge", {})
    assert r["amount"] == 14900
    assert sum(p["status"] == "paid" for p in s["payments"]) == 1   # одне списання лишилось
    with pytest.raises(PolicyError):
        tools.execute(s, "refund_duplicate_charge", {})


def test_duplicate_refund_blocked_when_no_duplicate(students):
    with pytest.raises(PolicyError):
        tools.execute(students["s1"], "refund_duplicate_charge", {})


def test_grant_access_requires_payment_and_inactive(students):
    s = students["s2"]
    tools.execute(s, "grant_access", {})
    assert s["access_active"]
    with pytest.raises(PolicyError, match="уже активний"):
        tools.execute(s, "grant_access", {})


def test_certificate_requires_all_lessons(students):
    with pytest.raises(PolicyError):
        tools.execute(students["s4"], "issue_certificate", {})
    tools.execute(students["s5"], "issue_certificate", {})
    assert students["s5"]["certificate_issued"]


def test_escalation_validates_team(students):
    with pytest.raises(PolicyError, match="Невідома команда"):
        tools.execute(students["s1"], "escalate_to_human", {"team": "ceo"})
    tools.execute(students["s1"], "escalate_to_human", {"team": "billing", "reason": "x"})
    assert students["s1"]["escalations"]


def test_unknown_tool_is_rejected(students):
    with pytest.raises(PolicyError, match="Невідома дія"):
        tools.execute(students["s1"], "drop_database", {})


def test_garbage_args_do_not_crash(students):
    tools.execute(students["s1"], "extend_deadline", {"days": "abc"})  # → дефолт 5
    assert students["s1"]["deadline_extra_days"] == 5
