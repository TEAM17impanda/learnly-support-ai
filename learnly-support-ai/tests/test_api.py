"""Наскрізні сценарії через HTTP API."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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
    assert client.post("/api/tickets", json={"student_id": "s1", "message": "   "}).status_code == 422


def test_blank_follow_up_and_reply_rejected():
    t = new_ticket("s1", "Хочу повернути гроші")
    assert client.post(f"/api/tickets/{t['id']}/messages",
                       json={"role": "student", "text": "   "}).status_code == 422
    assert client.post(f"/api/tickets/{t['id']}/send-reply",
                       json={"text": "   "}).status_code == 422


def test_role_chat_rejects_unknown_role():
    assert client.post("/api/role-chat", json={"role": "admin", "message": "Привіт"}).status_code == 422


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


def test_follow_up_keeps_executed_actions():
    t = new_ticket("s1", "Хочу повернути гроші за курс")
    a = rec_action(t)
    client.post(f"/api/tickets/{t['id']}/actions/{a['id']}/approve")
    r = client.post(f"/api/tickets/{t['id']}/messages",
                    json={"role": "student", "text": "Дякую! А сертифікат буде?"}).json()
    kept = next(x for x in r["actions"] if x["id"] == a["id"])
    assert kept["status"] == "executed"
    assert client.get("/api/analytics").json()["retention"]["saved"] == 1


def test_escalation_resolution_note_matches_problem():
    client.post("/api/role-chat", json={"role": "parent", "message": "Хочу додати другу доньку"})
    esc = next(e for e in client.get("/api/admin/escalations").json() if "дитини" in e["problem"])
    note = client.post(f"/api/admin/escalations/{esc['id']}/resolve").json()["resolution_note"]
    assert "баланс" not in note


def test_admin_ticket_lifecycle_and_result_returns_to_user_chat():
    """Концепція, розд. 3: тікет → взяти в роботу → рішення → результат в історії користувача."""
    client.post("/api/role-chat", json={"role": "parent", "message": "Оплата пройшла, а баланс 0"})
    r = client.post("/api/role-chat", json={"role": "parent", "message": "oksana.shevchenko@gmial.com"}).json()
    esc_id = r["escalated_ticket"]["id"]
    esc = client.get(f"/api/admin/escalations/{esc_id}").json()
    for field in ("user_name", "user_role", "original_message", "problem", "verified_context",
                  "checked_by_ai", "escalation_reason", "priority", "status"):
        assert esc[field]
    assert esc["status"] == "pending" and esc["team"] == "finance"

    taken = client.post(f"/api/admin/escalations/{esc_id}/take", json={"admin_name": "Ірина"}).json()
    assert taken["status"] == "in_progress" and taken["assignee"] == "Ірина"
    assert client.post(f"/api/admin/escalations/{esc_id}/take").status_code == 409

    done = client.post(f"/api/admin/escalations/{esc_id}/resolve",
                       json={"resolution": "Зараховано 8 занять"}).json()
    assert done["status"] == "resolved" and done["resolution"] == "Зараховано 8 занять"
    assert [h["event"] for h in done["history"]] == ["created", "taken", "fix_executed", "resolved"]
    assert client.post(f"/api/admin/escalations/{esc_id}/resolve").status_code == 409

    updates = client.post("/api/role-chat/updates?role=parent").json()
    assert [u["id"] for u in updates] == [esc_id]
    assert client.post("/api/role-chat/updates?role=parent").json() == []   # доставляється один раз
    events = [a["event"] for a in client.get("/api/audit").json()]
    assert {"escalation_created", "escalation_taken", "escalation_resolved"} <= set(events)


def test_admin_queue_filters_and_stats():
    client.post("/api/admin/escalations/ESC-102/resolve")
    assert [e["id"] for e in client.get("/api/admin/escalations?status=resolved").json()] == ["ESC-102"]
    assert all(e["priority"] == "P1" for e in client.get("/api/admin/escalations?priority=P1").json())
    st = client.get("/api/admin/stats").json()
    assert st["resolved"] == 1 and st["pending"] == 1 and st["p1_open"] == 1
    assert client.get("/api/admin/escalations/ESC-999").status_code == 404


@pytest.mark.parametrize("role", ["student", "teacher", "parent"])
@pytest.mark.parametrize("text", ["привіт", "помий підлогу"])
def test_role_chat_does_not_force_scenario_on_unrelated_message(role, text):
    """Раніше будь-яке повідомлення падало в «else»-сценарій, а в батьків ще й створювало тікет."""
    before = len(client.get("/api/admin/escalations").json())
    r = client.post("/api/role-chat", json={"role": role, "message": text}).json()
    assert r["decision_type"] == "needs_clarification" and r["source"] == "rules"
    assert r["intent"] == ("greeting" if text == "привіт" else "unclear")
    assert "синхронізувала" not in r["ai_reply"] and "ESC-" not in r["ai_reply"]
    assert len(client.get("/api/admin/escalations").json()) == before


@pytest.mark.parametrize("role,text,intent", [
    ("student", "Не можу увійти, не приходить код SMS", "auth_issue"),
    ("student", "Здав домашнє завдання, а пише що не здано", "homework_sync_issue"),
    ("teacher", "На п'ятницю 17:00 два учні в одному слоті", "double_booking"),
    ("teacher", "Артем Литвин завершив курс, а досі займає слот", "stale_record"),
    ("parent", "Гроші списали, а баланс занять 0", "payment_missing"),
    ("parent", "Не можу додати профіль доньки", "sibling_profile_issue"),
])
def test_role_chat_recognises_known_scenarios(role, text, intent):
    assert client.post("/api/role-chat", json={"role": role, "message": text}).json()["intent"] == intent


def test_state_survives_restart(tmp_path):
    """Стан зберігається в SQLite і піднімається новим процесом (тут — новим State)."""
    from app.db import Database
    from app.store import State

    path = str(tmp_path / "learnly.db")
    st = State(Database(path))
    assert st.load() is False                        # порожня база → потрібен seed
    st.students["s1"]["extensions_used"] = 2
    st.tickets["T-1"] = {"id": "T-1", "student_id": "s1", "status": "open", "messages": []}
    st.escalations[0]["status"] = "resolved"
    st.new_esc_id()
    st.log("test_event", x=1)
    st.save()

    again = State(Database(path))
    assert again.load() is True
    assert again.students["s1"]["extensions_used"] == 2
    assert again.tickets["T-1"]["status"] == "open"
    assert again.escalations[0]["status"] == "resolved"
    assert again.new_esc_id() == "ESC-104"           # лічильники ID не повторюються після рестарту
    assert again.audit[-1] == {"ts": again.audit[-1]["ts"], "event": "test_event", "x": 1}


def test_api_changes_are_written_to_db():
    from app.store import STATE
    client.post("/api/admin/escalations/ESC-101/take", json={"admin_name": "Ірина"})
    row = STATE.db.conn.execute("SELECT status FROM escalations WHERE id = 'ESC-101'").fetchone()
    assert row == ("in_progress",)


def test_role_chat_handles_joke_and_sarcasm():
    joke = client.post("/api/role-chat", json={"role": "student", "message": "помий підлогу хаха"}).json()
    assert joke["tone"] == "joke" and "жарт" in joke["ai_reply"]

    sarcasm = client.post("/api/role-chat", json={
        "role": "student", "message": "Супер платформа, знову не приходить код SMS"}).json()
    assert sarcasm["intent"] == "auth_issue" and sarcasm["tone"] == "sarcasm"   # суть розпізнана
    assert sarcasm["ai_reply"].startswith("Розумію, що ситуація неприємна")



# ---------- MCP-шлюз і сценарій «оплата на пошту з одруківкою» ----------
def test_mcp_gateway_enforces_access_rules():
    from app import mcp
    acc = mcp.call("get_account", "agent", account_id="acc-oksana")
    assert acc["ok"] and "password_hash" not in acc["result"] and "phone" not in acc["result"]
    pays = mcp.call("find_payments", "agent", card_last4="4417")
    assert pays["ok"] and all("card_number" not in x for x in pays["result"])
    assert not mcp.call("find_payments", "agent")["ok"]                                   # без фільтра — заборонено
    assert not mcp.call("drop_table", "agent")["ok"]                                       # поза білим списком
    denied = mcp.call("link_payment", "agent", payment_id="TX-9842", account_id="acc-oksana")
    assert not denied["ok"] and "agent" in denied["summary"]                               # запис — лише admin
    assert not mcp.call("get_account", "agent", account_id="acc-oksana", password_hash="x")["ok"]
    events = [a for a in client.get("/api/audit").json() if a["event"] == "mcp_call"]
    assert len(events) >= 5                                                                # кожен виклик в аудиті


def test_payment_wrong_email_flow_with_clarification_memory_and_admin_fix():
    """Ментор: ~40% звернень — оплата на неправильну пошту. Людина не знає про одруківку, тож агент
    сам знаходить платіж за сумою й схожою поштою, перевіряє власника (4 цифри картки), пам'ятає контекст,
    сам фінанси не чіпає, адміністратор виконує готове рішення одним кліком."""
    first = client.post("/api/role-chat", json={"role": "parent",
                        "message": "Сплатила 2400 грн за 8 уроків, а баланс 0 занять!"}).json()
    assert first["decision_type"] == "needs_clarification" and "escalated_ticket" not in first
    assert [c["tool"] for c in first["checks"]] == ["get_account", "find_payments", "find_payments"]
    assert "oks***@gmial.com" in first["ai_reply"] and "4417" not in first["ai_reply"]  # не розкриває картку
    assert len(client.get("/api/admin/escalations").json()) == 2                       # тікет ще не створено

    vague = client.post("/api/role-chat", json={"role": "parent", "message": "не пам'ятаю точно"}).json()
    assert vague["decision_type"] == "needs_clarification"                             # пам'ятає, що чекає картку

    r = client.post("/api/role-chat", json={"role": "parent", "message": "4417"}).json()
    esc = r["escalated_ticket"]
    assert r["decision_type"] == "escalated_to_admin" and "одруківк" in r["ai_reply"]
    assert esc["priority"] == "P1" and esc["proposed_fix"]["args"]["payment_id"] == "TX-9842"
    assert [c["tool"] for c in esc["agent_checks"]][-1] == "link_payment"
    assert esc["agent_checks"][-1]["ok"] is False                                       # агенту шлюз не дав

    done = client.post(f"/api/admin/escalations/{esc['id']}/resolve").json()
    assert "+8 занять" in done["resolution"]
    from app import mcp
    assert mcp.call("get_account", "admin", account_id="acc-oksana")["result"]["lessons_balance"] == 8
    updates = client.post("/api/role-chat/updates?role=parent").json()
    assert [u["id"] for u in updates] == [esc["id"]]                                   # Оксана бачить рішення


def test_payment_card_digits_and_new_problem_resets_pending():
    client.post("/api/role-chat", json={"role": "parent", "message": "Гроші списали, а занять немає"})
    r = client.post("/api/role-chat", json={"role": "parent", "message": "картка закінчується на 4417"}).json()
    assert r["escalated_ticket"]["proposed_fix"]["args"]["payment_id"] == "TX-9842"
    client.post("/api/role-chat", json={"role": "parent", "message": "Гроші списали, а занять немає"})
    other = client.post("/api/role-chat", json={"role": "parent", "message": "Хочу додати профіль доньки"}).json()
    assert other["intent"] == "sibling_profile_issue"                                  # нова тема скасувала уточнення


def test_payment_found_by_agent_but_card_mismatch_goes_to_manual_check():
    client.post("/api/role-chat", json={"role": "parent", "message": "Оплатила 2 400 грн, а занять 0"})
    r = client.post("/api/role-chat", json={"role": "parent", "message": "1111"}).json()
    esc = r["escalated_ticket"]
    assert esc["proposed_fix"] is None                                                 # без підтвердження — ніяких фіксів
    assert "не збіглися" in esc["verified_context"]
    assert "link_payment" not in [c["tool"] for c in esc["agent_checks"]]
