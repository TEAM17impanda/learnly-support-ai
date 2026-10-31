"""Тести для AI-агента викладача (Teacher Agent) та пов'язаних API ендпоінтів."""
try:
    import pytest
except ImportError:
    pytest = None

from fastapi.testclient import TestClient

from app.main import app
from app.store import STATE
from app import teacher_agent

client = TestClient(app)


def reset_state():
    client.post("/api/reset")
    client.post("/api/teacher-chat/reset-calendar")


if pytest:
    reset_fixture = pytest.fixture(autouse=True)(reset_state)


def test_detect_teacher_intent():
    assert teacher_agent.detect_teacher_intent("У мене подвійне бронювання на 17:00") == "double_booking"
    assert teacher_agent.detect_teacher_intent("Двоє учнів стоять в один час, є конфлікт") == "double_booking"
    assert teacher_agent.detect_teacher_intent("Артем Литвин завершив курс, але досі в розкладі") == "stale_record"
    assert teacher_agent.detect_teacher_intent("Слот у вівторок 16:00 застарілий") == "stale_record"
    assert teacher_agent.detect_teacher_intent("Як мені завантажити навчальні матеріали?") == "other"


def test_analyze_double_booking_priority_by_time():
    calendar = {
        "conflicted_slot": "П'ятниця 17:00",
        "students": [
            {"name": "Марк Бондар", "booked_at": "10:18"},
            {"name": "Денис Коваль", "booked_at": "10:15"},
        ],
        "alternatives": ["Субота 11:00", "Субота 14:00", "Понеділок 16:00"],
        "resolved": False,
    }
    res = teacher_agent.analyze_double_booking(calendar)
    assert res["intent"] == "double_booking"
    assert res["status"] == "conflict_detected"
    assert res["verified_context"]["primary_student"]["name"] == "Денис Коваль"
    assert res["verified_context"]["conflict_student"]["name"] == "Марк Бондар"
    assert "Субота 11:00" in res["verified_context"]["alternatives"]
    assert len(res["guardrails"]) >= 3
    assert res["proposed_actions"][0]["recommended"] is True


def test_analyze_double_booking_already_resolved():
    calendar = {
        "conflicted_slot": "П'ятниця 17:00",
        "students": [
            {"name": "Денис Коваль", "booked_at": "10:15"},
            {"name": "Марк Бондар", "booked_at": "10:18"},
        ],
        "alternatives": ["Субота 11:00"],
        "resolved": True,
        "final_resolution": "Конфлікт вирішено: Денис на Пт, Марк на Сб.",
    }
    res = teacher_agent.analyze_double_booking(calendar)
    assert res["status"] == "resolved"
    assert res["decision_type"] == "already_resolved"
    assert len(res["proposed_actions"]) == 0


def test_api_teacher_chat_double_booking():
    r = client.post("/api/teacher-chat", json={"message": "У мене два учні на п'ятницю 17:00"})
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "teacher"
    assert data["intent"] == "double_booking"
    assert "Денис Коваль" in data["ai_reply"]
    assert "Марк Бондар" in data["ai_reply"]


def test_api_teacher_chat_resolve_booking_custom_choice():
    # Викладач вирішує зберегти Марка, а перенести Дениса на Понеділок 16:00
    r = client.post("/api/teacher-chat/resolve-booking", json={
        "chosen_slot": "Понеділок 16:00",
        "student_to_move": "Денис Коваль",
        "student_to_keep": "Марк Бондар"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "Марк Бондар залишився на П'ятниця 17:00" in data["message"]
    assert "Денис Коваль перенесено на Понеділок 16:00" in data["message"]
    assert data["calendar"]["resolved"] is True


def test_api_teacher_student_card():
    r = client.get("/api/teacher/students/Денис%20Коваль")
    assert r.status_code == 200
    s = r.json()
    assert s["name"] == "Денис Коваль"
    assert s["grade"] == "2 клас"
    assert "+380" in s["parent_phone"]
    assert s["balance_lessons"] == 16

    # Невідомий учень -> 404
    r_err = client.get("/api/teacher/students/Невідомий%20Учень")
    assert r_err.status_code == 404


def test_api_teacher_stale_escalation_and_admin_sync():
    # 1. Викладач повідомляє про застарілий запис
    chat_r = client.post("/api/teacher-chat", json={"message": "Артем Литвин завершив курс, але досі в розкладі"})
    assert chat_r.status_code == 200
    assert chat_r.json()["intent"] == "stale_record"

    # 2. Викладач підтверджує ескалацію
    esc_r = client.post("/api/teacher-chat/escalate-stale", json={"confirm": True})
    assert esc_r.status_code == 200
    assert esc_r.json()["ok"] is True
    assert esc_r.json()["calendar"]["stale_escalated"] is True

    # 3. Адміністратор закриває тікет ESC-102
    resolve_r = client.post("/api/admin/escalations/ESC-102/resolve")
    assert resolve_r.status_code == 200
    assert resolve_r.json()["status"] == "resolved"

    # 4. Перевіряємо стан календаря вчителя - слот має бути позначений як звільнений
    cal_r = client.get("/api/teacher-chat/calendar")
    assert cal_r.status_code == 200
    assert cal_r.json()["calendar"]["stale_resolved"] is True

    # 5. При повторному аналізі агент підтверджує, що слот звільнено
    recheck_r = client.post("/api/teacher-chat", json={"message": "Що з Артемом Литвином?"})
    assert recheck_r.status_code == 200
    assert recheck_r.json()["status"] == "resolved"


def test_api_teacher_reset_calendar():
    # Змінюємо стан
    client.post("/api/teacher-chat/resolve-booking", json={
        "chosen_slot": "Субота 11:00",
        "student_to_move": "Марк Бондар"
    })
    cal = client.get("/api/teacher-chat/calendar").json()
    assert cal["calendar"]["resolved"] is True

    # Скидаємо розклад
    reset_r = client.post("/api/teacher-chat/reset-calendar")
    assert reset_r.status_code == 200
    assert reset_r.json()["ok"] is True
    assert reset_r.json()["calendar"]["resolved"] is False
