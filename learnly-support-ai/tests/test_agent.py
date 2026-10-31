"""Тести логіки розуміння. Очікування взяті з бізнес-правил (docs/.../business-context.md)."""
import pytest

from app import agent
from app.data import DEMO_MESSAGES, fresh_students


@pytest.fixture
def students():
    return fresh_students()


def tools_of(result, only_recommended=False):
    return [a["tool"] for a in result["actions"] if a["recommended"] or not only_recommended]


@pytest.mark.parametrize("text,intent", [
    ("Хочу повернути гроші за курс", "refund"),
    ("З мене списали гроші двічі!", "double_charge"),
    ("Не відкривається доступ до уроків", "access"),
    ("Коли буде мій сертифікат?", "certificate"),
    ("Не встигаю, можна продовжити дедлайн?", "deadline"),
    ("Де знайти запис вебінару?", "other"),
])
def test_detect_intent(text, intent):
    assert agent.detect_intent(text) == intent


def test_refund_request_with_good_pace_is_really_about_time(students):
    """Олена: 9/12 уроків за планом, оплата 5 днів тому → не повернення, а перенос потоку."""
    r = agent.heuristic_analyze(students["s1"], DEMO_MESSAGES["s1"])
    assert r["intent"] == "refund"
    assert r["true_goal"] == "needs_more_time"
    assert tools_of(r, only_recommended=True) == ["transfer_cohort"]
    assert "request_refund" in tools_of(r)            # але як запасний варіант
    refund = next(a for a in r["actions"] if a["tool"] == "request_refund")
    assert refund["recommended"] is False


def test_refund_request_from_disengaged_student_is_approved_refund(students):
    """Андрій: 2/10 уроків, 12 днів з оплати → у вікні, повернення обґрунтоване."""
    r = agent.heuristic_analyze(students["s4"], DEMO_MESSAGES["s4"])
    assert r["true_goal"] == "disengaged_or_mismatch"
    assert tools_of(r, only_recommended=True) == ["request_refund"]
    assert r["churn_risk"] >= 70


def test_refund_outside_window_is_never_recommended(students):
    """Дмитро: оплата 30 днів тому → вікно 14 днів закрите → лише ескалація людині."""
    r = agent.heuristic_analyze(students["s6"], DEMO_MESSAGES["s6"])
    assert "request_refund" not in tools_of(r)
    assert tools_of(r, only_recommended=True) == ["escalate_to_human"]


def test_double_charge_refunds_only_the_duplicate(students):
    r = agent.heuristic_analyze(students["s3"], DEMO_MESSAGES["s3"])
    assert r["intent"] == "double_charge"
    assert r["sentiment"] == "angry"
    assert tools_of(r, only_recommended=True) == ["refund_duplicate_charge"]
    assert r["priority"]["label"] == "P1"
    assert "14900" in "".join(r["reasoning"]) or "14900" in r["suggested_reply"]


def test_double_charge_complaint_without_duplicate_goes_to_billing(students):
    r = agent.heuristic_analyze(students["s1"], "З мене списали гроші двічі!")
    assert tools_of(r) == ["escalate_to_human"]


def test_access_problem_with_valid_payment_restores_access(students):
    r = agent.heuristic_analyze(students["s2"], DEMO_MESSAGES["s2"])
    assert r["true_goal"] == "access_problem"
    assert tools_of(r, only_recommended=True) == ["grant_access"]


def test_certificate_only_when_all_lessons_done(students):
    done = agent.heuristic_analyze(students["s5"], DEMO_MESSAGES["s5"])
    assert tools_of(done, only_recommended=True) == ["issue_certificate"]
    not_done = agent.heuristic_analyze(students["s4"], "Коли буде мій сертифікат?")
    assert tools_of(not_done) == []


def test_unclear_message_asks_clarification_and_does_not_act_on_its_own(students):
    r = agent.heuristic_analyze(students["s1"], "Де знайти запис вебінару?")
    assert r["intent"] == "other"
    assert tools_of(r, only_recommended=True) == []
    assert "уточніть" in r["suggested_reply"].lower()


def test_time_pressure_phrase_overrides_pace(students):
    s = students["s4"]  # поганий темп, але сам каже, що проблема в часі
    r = agent.heuristic_analyze(s, "Хочу повернути гроші, не встигаю, немає часу")
    assert r["true_goal"] == "needs_more_time"


def test_analyze_falls_back_to_rules_without_api_key(students, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    r = agent.analyze(students["s1"], DEMO_MESSAGES["s1"])
    assert r["source"] == "rules"


def test_analyze_falls_back_when_llm_fails(students, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setattr(agent, "llm_analyze", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    r = agent.analyze(students["s1"], DEMO_MESSAGES["s1"])
    assert r["source"] == "rules"
    assert "boom" in r["llm_error"]
    assert r["actions"]  # користувач все одно отримав аналіз


def test_priority_and_churn_are_bounded(students):
    for sid, msg in DEMO_MESSAGES.items():
        r = agent.heuristic_analyze(students[sid], msg)
        assert 0 <= r["churn_risk"] <= 100
        assert r["priority"]["label"] in ("P1", "P2", "P3")


def test_needs_time_reply_does_not_offer_unavailable_transfer(students):
    """Олена вже переносилась і поза вікном повернення → не обіцяємо перенос «на None» і повернення."""
    s = students["s1"]
    s["transferred"] = True
    s["payments"][0]["date"] = "2000-01-01"
    r = agent.heuristic_analyze(s, DEMO_MESSAGES["s1"])
    assert r["true_goal"] == "needs_more_time"
    assert tools_of(r, only_recommended=True) == ["extend_deadline"]
    assert "None" not in r["suggested_reply"]
    assert "потік" not in r["suggested_reply"]
    assert "оформимо повернення" not in r["suggested_reply"]


def test_llm_clarifying_answer_without_actions_is_accepted(students, monkeypatch):
    """Промпт дозволяє actions: [] для уточнюючого питання — це не збій LLM."""
    monkeypatch.setattr(agent, "_extract_json", lambda text: {
        "intent": "other", "true_goal": "unknown", "sentiment": "neutral",
        "reasoning": "Недостатньо даних", "reply": "Уточніть, будь ласка, деталі.", "actions": []})

    class FakeModels:
        def generate_content(self, **kwargs):
            return type("R", (), {"text": "{}"})()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    from google import genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    r = agent.llm_analyze(students["s1"], "Привіт")
    assert r["source"] == "llm" and r["actions"] == []
    assert r["reasoning"] == ["Недостатньо даних"]
