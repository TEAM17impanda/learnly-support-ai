"""Наскрізні сценарії через HTTP API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client.post("/api/reset")
    client.post("/api/settings", json={"autonomy": "copilot"})


def new_ticket(sid, msg):
    r = client.post("/api/tickets", json={"student_id": sid, "message": msg})
    assert r.status_code == 200
    return r.json()


def rec_action(t):
    return next(a for a in t["actions"] if a["recommended"])


def test_seed_has_open_tickets_sorted_by_priority_and_s1_is_free_for_demo():
    items = client.get("/api/tickets").json()
    open_items = [i for i in items if i["status"] == "open"]
    assert open_items and all(i["student"] != "Олена Коваль" for i in open_items)
    scores = [i["priority"]["score"] for i in open_items]
    assert scores == sorted(scores, reverse=True)
    assert open_items[0]["priority"]["label"] == "P1"   # Ірина (злюча, дубль)


def test_main_demo_flow_saves_student_from_refund():
    """Олена просить повернення → AI пропонує перенос → агент підтверджує → рахується як врятована."""
    t = new_ticket("s1", "Хочу повернути гроші за курс")
    assert t["analysis"]["true_goal"] == "needs_more_time"
    a = rec_action(t)
    assert a["tool"] == "transfer_cohort" and a["requires_approval"]
    assert t["student_context"]["cohort"] == "PY-OCT"           # ще нічого не змінилось

    done = client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/approve").json()
    assert done["status"] == "resolved" and done["resolved_by"] == "agent"
    assert done["student_context"]["cohort"] == "PY-NOV"
    assert any("перенесено" in m["text"] for m in done["messages"] if m["role"] == "system")

    an = client.get("/api/analytics").json()
    assert an["retention"]["saved"] == 1
    assert an["retention"]["saved_amount"] == 9900


def test_double_approve_returns_409():
    t = new_ticket("s1", "Хочу повернути гроші")
    a = rec_action(t)
    assert client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/approve").status_code == 200
    assert client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/approve").status_code == 409


def test_reject_does_not_change_student():
    t = new_ticket("s1", "Хочу повернути гроші")
    a = rec_action(t)
    r = client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/reject").json()
    assert r["status"] == "open"
    assert r["student_context"]["cohort"] == "PY-OCT"
    assert next(x for x in r["actions"] if x["id"] == a["id"])["status"] == "rejected"


def test_policy_guard_blocks_stale_action():
    """Дію запропоновано, але до підтвердження ситуація змінилась → policy блокує."""
    t = new_ticket("s1", "Хочу повернути гроші")
    a = rec_action(t)
    # хтось уже переніс учня іншим шляхом
    t2 = new_ticket("s1", "Хочу перейти на наступний потік")
    client.post(f"/api/tickets/{t2['id']}/actions/{rec_action(t2)['id']}/approve")
    r = client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/approve").json()
    failed = next(x for x in r["actions"] if x["id"] == a["id"])
    assert failed["status"] == "failed" and "один раз" in failed["error"]


def test_autonomy_auto_low_risk_executes_only_low_risk():
    client.post("/api/settings", json={"autonomy": "auto_low_risk"})
    access = new_ticket("s2", "Не відкривається доступ до курсу")
    assert rec_action(access)["status"] == "executed"
    assert rec_action(access)["executed_by"] == "ai"
    assert access["student_context"]["access_active"] is True

    dup = new_ticket("s3", "Списали двічі!")
    assert rec_action(dup)["status"] == "proposed"       # high risk чекає людину
    assert dup["student_context"]["duplicate_ids"]


def test_invalid_autonomy_rejected():
    assert client.post("/api/settings", json={"autonomy": "yolo"}).status_code == 422


def test_unknown_student_and_ticket():
    assert client.post("/api/tickets", json={"student_id": "nope", "message": "hi"}).status_code == 404
    assert client.get("/api/tickets/T-0").status_code == 404


def test_empty_message_rejected():
    assert client.post("/api/tickets", json={"student_id": "s1", "message": ""}).status_code == 422


def test_reply_quality_is_scored_and_ai_draft_beats_rude_reply():
    t = new_ticket("s1", "Хочу повернути гроші")
    rude = client.post(f"/api/tickets/{t['id']}/send-reply",
                       json={"text": "Читайте правила на сайті.", "agent_name": "Влад"}).json()
    good = client.post(f"/api/tickets/{t['id']}/send-reply",
                       json={"text": t["analysis"]["suggested_reply"], "from_ai_draft": True,
                             "agent_name": "Марія"}).json()
    q_rude = [m for m in rude["messages"] if m["role"] == "agent"][-1]["quality"]["score"]
    q_good = [m for m in good["messages"] if m["role"] == "agent"][-1]["quality"]["score"]
    assert q_rude < 40 < 80 <= q_good
    an = client.get("/api/analytics").json()
    assert an["quality"]["avg_ai_draft"] >= an["quality"]["avg_manual"]


def test_new_student_message_triggers_reanalysis():
    t = new_ticket("s4", "Привіт")
    assert t["analysis"]["intent"] == "other"
    r = client.post(f"/api/tickets/{t['id']}/messages",
                    json={"role": "student", "text": "Хочу повернути гроші"}).json()
    assert r["analysis"]["intent"] == "refund"


def test_reset_restores_state():
    t = new_ticket("s1", "Хочу повернути гроші")
    client.post(f"/api/tickets/{t['id']}/actions/{rec_action(t)['id']}/approve")
    client.post("/api/reset")
    assert client.get("/api/students/s1").json()["cohort"] == "PY-OCT"
    assert client.get("/api/analytics").json()["retention"]["saved"] == 0


def test_health_and_index():
    assert client.get("/api/health").json()["ok"] is True
    page = client.get("/")
    assert page.status_code == 200 and "Learnly" in page.text
