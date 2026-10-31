"""REST API + роздача фронтенду."""
import asyncio
import copy
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

load_dotenv()

from . import agent, teacher_agent, tools  # noqa: E402
from .context import build_context  # noqa: E402
from .data import COURSES, DEMO_MESSAGES, HISTORY, INITIAL_CALENDAR, TEACHER_STUDENTS  # noqa: E402
from .quality import score_reply  # noqa: E402
from .store import STATE, now  # noqa: E402

app = FastAPI(title="Learnly Support AI")
_write_lock = asyncio.Lock()


@app.middleware("http")
async def persist_changes(request: Request, call_next):
    """Змінюючі запити виконуються по черзі; після кожного стан зберігається в SQLite."""
    if request.method == "GET":
        return await call_next(request)
    async with _write_lock:
        response = await call_next(request)
        STATE.save()
        return response
STATIC = Path(__file__).resolve().parent.parent / "static"
RETENTION_TOOLS = {"transfer_cohort", "extend_deadline", "book_mentor_session"}
MINUTES_PER_ACTION, MINUTES_PER_DRAFT = 4, 2  # оцінка ручної роботи, яку економить AI


# ---------------- моделі запитів ----------------
class NewTicket(BaseModel):
    student_id: str
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def message_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class Message(BaseModel):
    role: str = "student"  # student | agent
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    from_ai_draft: bool = False
    agent_name: str = "Агент"

    @field_validator("text")
    @classmethod
    def reply_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value


class Settings(BaseModel):
    autonomy: str


# ---------------- допоміжне ----------------
def _student(sid: str) -> dict:
    s = STATE.students.get(sid)
    if not s:
        raise HTTPException(404, "Учня не знайдено")
    return s


def _ticket(tid: str) -> dict:
    t = STATE.tickets.get(tid)
    if not t:
        raise HTTPException(404, "Звернення не знайдено")
    return t


def _msg(t: dict, role: str, text: str, **extra):
    t["messages"].append({"role": role, "text": text, "ts": now(), **extra})


def _run_analysis(t: dict, message: str):
    s = _student(t["student_id"])
    # історія без поточного повідомлення — воно передається окремо
    t["analysis"] = agent.analyze(s, message, t["messages"][:-1])
    # виконані/відхилені дії лишаються в історії тікета, замінюємо лише старі пропозиції
    t["actions"] = [a for a in t["actions"] if a["status"] != "proposed"] + t["analysis"].pop("actions")
    t.setdefault("initial_intent", t["analysis"]["intent"])  # для retention-метрик після follow-up
    STATE.log("analysis", ticket=t["id"], intent=t["analysis"]["intent"],
              goal=t["analysis"]["true_goal"], source=t["analysis"]["source"])
    _apply_autonomy(t)


def _apply_autonomy(t: dict):
    """auto_low_risk: low-risk рекомендовані дії виконуються без людини."""
    if STATE.settings["autonomy"] != "auto_low_risk":
        return
    for a in t["actions"]:
        if a["status"] == "proposed" and a["recommended"] and not a["requires_approval"]:
            _execute(t, a, by="ai")


def _execute(t: dict, a: dict, by: str):
    s = _student(t["student_id"])
    try:
        result = tools.execute(s, a["tool"], a["args"])
        a.update(status="executed", result=result, executed_by=by)
        _msg(t, "system", f"✅ {result['summary']} ({'AI автоматично' if by == 'ai' else 'підтверджено агентом'})")
        STATE.log("action_executed", ticket=t["id"], tool=a["tool"], by=by, result=result["summary"])
        if a["recommended"]:
            t["status"], t["resolved_by"] = "resolved", by
    except tools.PolicyError as e:
        a.update(status="failed", error=str(e))
        _msg(t, "system", f"⛔ Політика заблокувала дію «{a['title']}»: {e}")
        STATE.log("action_blocked", ticket=t["id"], tool=a["tool"], reason=str(e))


def _public_ticket(t: dict) -> dict:
    s = STATE.students[t["student_id"]]
    return {**t, "student": {"id": s["id"], "name": s["name"], "course": COURSES[s["course"]]["name"],
                             "cohort": s["cohort"]},
            "student_context": build_context(s)}


def _seed():
    """Історія для аналітики якості + відкриті звернення для демо (s1 лишаємо для live-демо)."""
    for h in HISTORY:
        s = STATE.students[h["student_id"]]
        t = {"id": STATE.new_ticket_id(), "student_id": s["id"], "status": "resolved",
             "resolved_by": "agent", "created": "історія", "messages": [], "actions": [],
             "analysis": None, "quality": []}
        _msg(t, "student", h["message"])
        q = score_reply(h["agent_reply"], s)
        _msg(t, "agent", h["agent_reply"], agent=h["agent"], quality=q, from_ai_draft=False)
        t["quality"].append({"agent": h["agent"], **q})
        t["analysis"] = agent.heuristic_analyze(s, h["message"])
        t["actions"] = []
        STATE.tickets[t["id"]] = t
    for sid in ("s2", "s3", "s4", "s5", "s6"):
        _new_ticket(sid, DEMO_MESSAGES[sid])


def _new_ticket(sid: str, message: str) -> dict:
    s = _student(sid)
    t = {"id": STATE.new_ticket_id(), "student_id": s["id"], "status": "open", "resolved_by": None,
         "created": now(), "messages": [], "actions": [], "analysis": None, "quality": []}
    _msg(t, "student", message)
    STATE.tickets[t["id"]] = t
    _run_analysis(t, message)
    return t


# ---------------- API ----------------
@app.get("/api/health")
def health():
    return {"ok": True, "llm": bool(os.getenv("GEMINI_API_KEY")), "autonomy": STATE.settings["autonomy"],
            "db": Path(STATE.db.path).name}


@app.get("/api/students")
def students():
    return [{"id": s["id"], "name": s["name"], "course": COURSES[s["course"]]["name"],
             "demo_message": DEMO_MESSAGES.get(s["id"], "")} for s in STATE.students.values()]


@app.get("/api/students/{sid}")
def student(sid: str):
    s = _student(sid)
    return {**s, "context": build_context(s)}


@app.get("/api/tickets")
def list_tickets():
    items = []
    for t in STATE.tickets.values():
        a = t["analysis"] or {}
        pr = a.get("priority", {"score": 0, "label": "P3"})
        s = STATE.students[t["student_id"]]
        items.append({"id": t["id"], "status": t["status"], "resolved_by": t["resolved_by"],
                      "student": s["name"], "course": COURSES[s["course"]]["name"],
                      "intent": a.get("intent"), "priority": pr, "churn_risk": a.get("churn_risk", 0),
                      "last": t["messages"][0]["text"][:90] if t["messages"] else "",
                      "created": t["created"]})
    items.sort(key=lambda x: (x["status"] != "open", -x["priority"]["score"]))
    return items


@app.post("/api/tickets")
def create_ticket(body: NewTicket):
    return _public_ticket(_new_ticket(body.student_id, body.message.strip()))


@app.get("/api/tickets/{tid}")
def get_ticket(tid: str):
    return _public_ticket(_ticket(tid))


@app.post("/api/tickets/{tid}/messages")
def add_message(tid: str, body: Message):
    t = _ticket(tid)
    if body.role not in ("student", "agent"):
        raise HTTPException(422, "role: student|agent")
    _msg(t, body.role, body.text.strip())
    if body.role == "student":
        t["status"] = "open"
        _run_analysis(t, body.text.strip())
    return _public_ticket(t)


@app.post("/api/tickets/{tid}/send-reply")
def send_reply(tid: str, body: Reply):
    t = _ticket(tid)
    s = _student(t["student_id"])
    q = score_reply(body.text, s)
    _msg(t, "agent", body.text, agent=body.agent_name, quality=q, from_ai_draft=body.from_ai_draft)
    t["quality"].append({"agent": body.agent_name, "from_ai_draft": body.from_ai_draft, **q})
    STATE.log("reply_sent", ticket=tid, score=q["score"], from_ai_draft=body.from_ai_draft)
    return _public_ticket(t)


def _find_action(t: dict, aid: str) -> dict:
    a = next((x for x in t["actions"] if x["id"] == aid), None)
    if not a:
        raise HTTPException(404, "Дію не знайдено")
    if a["status"] != "proposed":
        raise HTTPException(409, f"Дія вже має статус «{a['status']}»")
    return a


@app.post("/api/tickets/{tid}/actions/{aid}/approve")
def approve(tid: str, aid: str):
    t = _ticket(tid)
    _execute(t, _find_action(t, aid), by="agent")
    return _public_ticket(t)


@app.post("/api/tickets/{tid}/actions/{aid}/reject")
def reject(tid: str, aid: str):
    t = _ticket(tid)
    a = _find_action(t, aid)
    a["status"] = "rejected"
    _msg(t, "system", f"❌ Агент відхилив дію «{a['title']}»")
    STATE.log("action_rejected", ticket=tid, tool=a["tool"])
    return _public_ticket(t)


@app.get("/api/settings")
def get_settings():
    return STATE.settings


@app.post("/api/settings")
def set_settings(body: Settings):
    if body.autonomy not in ("copilot", "auto_low_risk"):
        raise HTTPException(422, "autonomy: copilot|auto_low_risk")
    STATE.settings["autonomy"] = body.autonomy
    STATE.log("settings", autonomy=body.autonomy)
    return STATE.settings


@app.post("/api/reset")
def reset():
    autonomy = STATE.settings["autonomy"]
    STATE.reset()
    STATE.settings["autonomy"] = autonomy
    _seed()
    return {"ok": True}


@app.get("/api/audit")
def audit():
    return STATE.audit[-100:]


@app.get("/api/analytics")
def analytics():
    tickets = list(STATE.tickets.values())
    by_intent, by_priority = {}, {"P1": 0, "P2": 0, "P3": 0}
    proposed = executed = executed_ai = blocked = 0
    refund_reqs = saved = 0
    saved_amount = 0
    scores, low_quality = [], 0
    draft_scores, manual_scores = [], []
    open_risks = []
    for t in tickets:
        a = t["analysis"] or {}
        if a.get("intent"):
            by_intent[a["intent"]] = by_intent.get(a["intent"], 0) + 1
            if t["status"] == "open" or t["actions"]:
                by_priority[a["priority"]["label"]] += 1
        if t["status"] == "open":
            open_risks.append(a.get("churn_risk", 0))
        for x in t["actions"]:
            proposed += 1
            executed += x["status"] == "executed"
            executed_ai += x["executed_by"] == "ai"
            blocked += x["status"] == "failed"
        if t.get("initial_intent", a.get("intent")) == "refund" and t["actions"]:
            refund_reqs += 1
            done = [x for x in t["actions"] if x["status"] == "executed"]
            if any(x["tool"] in RETENTION_TOOLS for x in done) and not any(
                    x["tool"] == "request_refund" for x in done):
                saved += 1
                saved_amount += a["context"]["amount_paid"]
        for q in t["quality"]:
            scores.append(q["score"])
            low_quality += q["score"] < 55
            (draft_scores if q.get("from_ai_draft") else manual_scores).append(q["score"])
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else None  # noqa: E731
    return {
        "total_tickets": len(tickets),
        "open": sum(t["status"] == "open" for t in tickets),
        "resolved": sum(t["status"] == "resolved" for t in tickets),
        "by_intent": by_intent, "by_priority": by_priority,
        "automation": {"proposed": proposed, "executed": executed, "executed_by_ai": executed_ai,
                       "blocked_by_policy": blocked},
        "retention": {"refund_requests": refund_reqs, "saved": saved, "saved_amount": saved_amount},
        "quality": {"avg": avg(scores), "count": len(scores), "low_quality": low_quality,
                    "avg_ai_draft": avg(draft_scores), "avg_manual": avg(manual_scores)},
        "avg_open_churn_risk": avg(open_risks),
        # історичні тікети агенти закрили без AI — не зараховуємо їх у зекономлений час
        "time_saved_min": executed * MINUTES_PER_ACTION
                          + sum(1 for t in tickets if t["analysis"] and t["status"] != "open"
                                and t["created"] != "історія") * MINUTES_PER_DRAFT,
        "note": "Оцінка часу — модельна (4 хв/дія + 2 хв/чернетка) на мок-даних.",
    }


class RoleChatMessage(BaseModel):
    role: str = Field(pattern="^(student|teacher|parent)$")
    scenario_id: str | None = None
    message: str

    @field_validator("message")
    @classmethod
    def role_message_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class TeacherChatMessage(BaseModel):
    message: str
    scenario_id: str | None = None


class ResolveBooking(BaseModel):
    chosen_slot: str = "Субота 11:00"
    student_to_move: str = "Марк Бондар"
    student_to_keep: str | None = None


class EscalateStale(BaseModel):
    confirm: bool = True


@app.get("/api/roles-data")
def roles_data():
    from .data import ROLE_PRESETS
    return {
        "roles": ROLE_PRESETS,
        "calendar": STATE.calendar,
        "escalations": STATE.escalations,
    }


@app.get("/api/teacher/students/{name}")
def teacher_student_card(name: str):
    """Детальна картка учня для викладача (контакти батьків, баланс, прогрес)."""
    s = TEACHER_STUDENTS.get(name)
    if not s:
        raise HTTPException(404, "Учня не знайдено")
    return s


@app.get("/api/teacher-chat/calendar")
def get_teacher_calendar():
    """Поточний стан календаря викладача та пов'язаного тікета."""
    return {
        "calendar": STATE.calendar,
        "escalation_102": next((e for e in STATE.escalations if e["id"] == "ESC-102"), None)
    }


@app.post("/api/teacher-chat/reset-calendar")
def reset_teacher_calendar():
    """Скидання стану розкладу вчителя до демо-конфлікту без впливу на інші ролі."""
    STATE.calendar = copy.deepcopy(INITIAL_CALENDAR)
    esc = next((e for e in STATE.escalations if e["id"] == "ESC-102"), None)
    if esc and esc["status"] != "pending":
        _reopen_escalation(esc, "Календар викладача скинуто до демо-конфлікту")
    STATE.log("teacher_calendar_reset")
    return {"ok": True, "calendar": STATE.calendar}


@app.post("/api/teacher-chat")
def teacher_chat(body: TeacherChatMessage):
    """Teacher-агент: аналізує повідомлення викладача та повертає структурований результат."""
    msg = body.message.strip()
    result = teacher_agent.analyze_teacher_message(msg, STATE.calendar)
    return {"role": "teacher", **result}


@app.post("/api/teacher-chat/resolve-booking")
def teacher_resolve_booking(body: ResolveBooking):
    """Підтвердження викладачем рішення конфлікту бронювання з динамічним вибором."""
    slot = STATE.calendar.get("conflicted_slot", "П'ятниця 17:00")
    students = [s["name"] for s in STATE.calendar.get("students", [])]
    to_move = body.student_to_move
    to_keep = body.student_to_keep or next((s for s in students if s != to_move), "Перший учень")

    STATE.calendar["resolved"] = True
    STATE.calendar["final_resolution"] = (
        f"{to_keep} залишився на {slot}. "
        f"{to_move} перенесено на {body.chosen_slot}. "
        f"Обом родинам надіслано SMS-підтвердження."
    )
    STATE.calendar["resolution_details"] = {
        "student_kept": to_keep,
        "student_moved": to_move,
        "original_slot": slot,
        "chosen_slot": body.chosen_slot,
    }
    STATE.log("teacher_conflict_resolved", slot=body.chosen_slot, student=to_move, kept=to_keep)
    return {
        "ok": True,
        "calendar": STATE.calendar,
        "message": STATE.calendar["final_resolution"],
        "actions_taken": [
            f"Слот {slot} закріплено за {to_keep}",
            f"{to_move} перенесено на {body.chosen_slot}",
            f"SMS-сповіщення надіслано родинам учнів {to_keep} та {to_move}",
            "Аудит-запис збережено в системі",
        ]
    }


@app.post("/api/teacher-chat/escalate-stale")
def teacher_escalate_stale(body: EscalateStale):
    """Підтвердження викладачем ескалації застарілого запису."""
    STATE.calendar["stale_escalated"] = True
    esc = next((e for e in STATE.escalations if e["id"] == "ESC-102"), None)
    if not esc:
        esc = _create_escalation(
            source_role="teacher", user_name="Олена Іванівна", category="Календар / застарілий запис",
            team="admin", original_message="Артем Литвин завершив курс, але досі займає слот у вівторок 16:00.",
            problem="Застарілий запис учня Артема Литвина після завершення курсу",
            verified_context="Курс завершено 7 днів тому (100% уроків пройдено). Запис у календарі активний.",
            checked_by_ai="Статус проходження курсу, сертифікацію, помилку вебхук-синхронізації",
            escalation_reason="Потрібна синхронізація з навчальним відділом щодо наступного модуля",
            priority="P2",
        )
        STATE.log("teacher_stale_escalated", esc_id=esc["id"])
    else:
        if esc["status"] != "pending":
            _reopen_escalation(esc, "Викладач повторно передав тікет адміністратору")
        STATE.log("teacher_stale_escalated_existing", esc_id=esc["id"])

    return {
        "ok": True,
        "escalation": esc,
        "calendar": STATE.calendar,
        "message": f"Тікет {esc['id']} передано до черги адміністратора для координації з навчальним відділом.",
    }


# сценарій спрацьовує лише за явними ознаками; інше — уточнення/відмова без дій і тікетів
ROLE_SCENARIOS = {
    "student": [
        ("auth", ["увійт", "вхід", "зайти", "логін", "парол", "код", "sms", "смс"]),
        ("homework", ["домашн", "дз", "завдання", "здав", "здала", "відправив", "відправила",
                      "надіслав", "надіслала", "не здан", "файл"]),
    ],
    "parent": [
        ("payment", ["оплат", "сплат", "баланс", "списал", "списан", "2400", "2,400", "платіж",
                     "гроші", "заплатил"]),
        ("sibling", ["дитин", "доньк", "дочк", "сина", "профіль", "сімейн"]),
    ],
}


def _detect_role_scenario(role: str, msg_l: str) -> str | None:
    if role == "teacher":  # у викладача власний агент і словники (teacher_agent.py)
        intent = teacher_agent.detect_teacher_intent(msg_l)
        return None if intent == "other" else intent
    words = set(re.findall(r"\w+", msg_l))
    for scenario, keys in ROLE_SCENARIOS[role]:
        # короткі ключі (дз, код) — лише цілим словом, щоб «кодування» не стало «кодом»
        if any((k in words) if len(k) <= 4 and k.isalpha() else (k in msg_l) for k in keys):
            return scenario
    return None


@app.post("/api/role-chat")
def role_chat(body: RoleChatMessage):
    msg = body.message.strip()
    tone = agent.detect_tone(msg)
    scenario = _detect_role_scenario(body.role, msg.lower())

    if scenario is None:
        reply, source = agent.role_reply(body.role, msg)
        STATE.log("role_chat_clarify", role=body.role, source=source, tone=tone)
        return {
            "role": body.role,
            "intent": "greeting" if agent.is_greeting(msg) else tone or "unclear",
            "intent_title": "Уточнення запиту",
            "decision_type": "needs_clarification",
            "source": source, "tone": tone,
            "ai_reply": reply,
        }

    res = _role_scenario_reply(body.role, scenario, msg)
    res["tone"] = tone
    if tone == "sarcasm":  # іронію не сприймаємо буквально — спершу визнаємо незручність
        res["ai_reply"] = "Розумію, що ситуація неприємна, — перепрошую за незручності. " + res["ai_reply"]
    return res


def _role_scenario_reply(role: str, scenario: str, msg: str) -> dict:
    if role == "teacher":
        STATE.log("teacher_role_chat", scenario=scenario)
        return {"role": role, **teacher_agent.analyze_teacher_message(msg, STATE.calendar)}

    elif role == "student":
        if scenario == "auth":
            STATE.log("student_auth_check", student="Денис Коваль")
            return {
                "role": role,
                "intent": "auth_issue",
                "intent_title": "Проблема з авторизацією / кодом",
                "verified_context": {
                    "account_status": "Активний",
                    "auth_method": "SMS verification (+380501234567)",
                    "gateway_status": "Затримка доставки SMS оператора (код 429)",
                },
                "checked_by_ai": "Логи шлюзу авторизації, блокування IP, статус облікового запису",
                "decision_type": "resolved_by_ai",
                "proposed_action": {
                    "title": "Надіслати резервний магічний лінк",
                    "description": "Одноразовий токен входу відправлено на підтверджений email",
                },
                "ai_reply": "Бачу, що ваш акаунт активний, але SMS-шлюз мобільного оператора тимчасово затримує доставку кодів. "
                            "Щоб ви не чекали, я надіслала одноразове безпечне посилання для миттєвого входу на ваш email (d****@example.com). "
                            "Перевірте пошту — лінк дійсний 15 хвилин!",
            }
        else:
            STATE.log("homework_check", student="Денис Коваль")
            return {
                "role": role,
                "intent": "homework_sync_issue",
                "intent_title": "Домашнє завдання не відображається",
                "verified_context": {
                    "attempt_time": "Вчора, 21:14",
                    "file_size": "2.4 MB (PDF)",
                    "upload_status": "Тимчасова помилка хмарного сховища (S3 timeout)",
                },
                "checked_by_ai": "Журнал спроб завантаження файлів, кеш чернетки у браузері",
                "decision_type": "resolved_by_ai",
                "proposed_action": {
                    "title": "Відновлення з чернетки",
                    "description": "Робота знайдена в локальному кеші платформи та автоматично надіслана викладачу",
                },
                "ai_reply": "Перевірила логи: вчора о 21:14 ви дійсно завантажували файл із ДЗ (2.4 MB), але сталася затримка синхронізації з хмарою. "
                            "Ваша чернетка збереглася! Я успішно синхронізувала файл із кабінетом викладача Олени Іванівни. Тепер статус: «Здано на перевірку».",
            }

    else:  # parent
        if scenario == "payment":
            new_esc = _create_escalation(
                source_role="parent", user_name="Оксана Шевченко", category="Оплата / нарахування занять",
                team="finance", original_message=msg,
                problem="Оплата 2,400 грн списана з картки, баланс уроків не поповнився",
                verified_context="Monobank транзакція TX-9842 успішна. Вебхук білінгу отримано, але статус обробки застряг.",
                checked_by_ai="Банківський шлюз (успішно), лог білінгу, баланс сім'ї (0 занять)",
                escalation_reason="Політика безпеки: фінансові нарахування потребують авторизації адміністратора",
                priority="P1",
            )
            esc_id = new_esc["id"]
            return {
                "role": role,
                "intent": "payment_missing",
                "intent_title": "Оплата успішна, заняття не з'явилися",
                "verified_context": {
                    "transaction": "TX-9842 (2,400 грн, Monobank)",
                    "bank_status": "Успішно списано",
                    "crm_balance": "0 занять (вебхук очікує підтвердження)",
                },
                "checked_by_ai": "Банківський шлюз, статус транзакції, чергу синхронізації оплат",
                "decision_type": "escalated_to_admin",
                "escalated_ticket": new_esc,
                "ai_reply": "Я перевірила банківський шлюз: оплата 2,400 грн пройшла успішно, але через затримку платіжного шлюзу заняття ще не відобразилися в кабінеті. "
                            f"Згідно з правилами фінансової безпеки школи, я не можу змінити баланс самостійно, тому я сформувала терміновий тікет P1 (№{esc_id}) для адміністратора. "
                            "Він уже взятий у чергу з найвищим пріоритетом!",
            }
        else:
            new_esc = _create_escalation(
                source_role="parent", user_name="Оксана Шевченко", category="Сімейний акаунт",
                team="admin", original_message=msg,
                problem="Не вдається додати профіль другої дитини (Марія, 6 років)",
                verified_context="Основний акаунт активний. Спроба створити сімейний профіль.",
                checked_by_ai="Наявність дублікатів у базі, сімейний тариф",
                escalation_reason="Потрібна ручна валідація сімейного зв'язку в CRM адміністратором",
                priority="P2",
            )
            esc_id = new_esc["id"]
            return {
                "role": role,
                "intent": "sibling_profile_issue",
                "intent_title": "Додавання другої дитини до акаунта",
                "verified_context": {
                    "parent_account": "Оксана Шевченко (перевірено)",
                    "target_child": "Марія Шевченко (6 років)",
                },
                "checked_by_ai": "Наявність дублікатів у базі, сімейний тариф",
                "decision_type": "escalated_to_admin",
                "escalated_ticket": new_esc,
                "ai_reply": "Перевірила дані: для активації сімейного профілю для другої дитини (Марії) потрібна підтверджуюча прив'язка в базі школи. "
                            f"Я передала запит адміністратору (Тікет №{esc_id}), профіль буде підключено протягом кількох хвилин!",
            }


@app.post("/api/role-chat/resolve-booking")
def resolve_booking(body: ResolveBooking):
    return teacher_resolve_booking(body)


# ---------------- адмінка: черга ескалацій ----------------
ROLE_LABELS = {"student": "Учень", "teacher": "Викладач", "parent": "Батьки"}
ESC_STATUSES = ("pending", "in_progress", "resolved")
DEFAULT_RESOLUTIONS = {
    "finance": "Транзакцію підтверджено, заняття зараховано на баланс.",
    "tech": "Технічну проблему усунено, доступ перевірено.",
    "admin": "Запит опрацьовано вручну адміністратором.",
    "teacher": "Навчальний відділ погодив звільнення слота. Слот Вівторок 16:00 звільнено.",
}


class TakeEscalation(BaseModel):
    admin_name: str = Field("Адміністратор", min_length=1, max_length=80)


class ResolveEscalation(BaseModel):
    admin_name: str = Field("Адміністратор", min_length=1, max_length=80)
    resolution: str | None = Field(None, max_length=1000)


def _create_escalation(*, source_role: str, user_name: str, category: str, team: str,
                       original_message: str, problem: str, verified_context: str,
                       checked_by_ai: str, escalation_reason: str, priority: str) -> dict:
    """Структурований тікет для адміністратора (поля — за концепцією, розділ 3)."""
    ts = now()
    esc = {
        "id": STATE.new_esc_id(), "source_role": source_role, "user_name": user_name,
        "user_role": ROLE_LABELS[source_role], "category": category, "team": team,
        "original_message": original_message, "problem": problem,
        "verified_context": verified_context, "checked_by_ai": checked_by_ai,
        "escalation_reason": escalation_reason, "priority": priority,
        "status": "pending", "created_at": ts, "updated_at": ts,
        "assignee": None, "resolution": None, "delivered": False,
        "history": [{"ts": ts, "event": "created", "by": "AI Support Agent",
                     "note": "Тікет створено AI-агентом"}],
    }
    STATE.escalations.append(esc)
    STATE.log("escalation_created", esc_id=esc["id"], role=source_role, priority=priority, team=team)
    return esc


def _escalation(esc_id: str) -> dict:
    esc = next((e for e in STATE.escalations if e["id"] == esc_id), None)
    if not esc:
        raise HTTPException(404, "Тікет не знайдено")
    return esc


def _esc_event(esc: dict, event: str, by: str, note: str):
    esc["updated_at"] = now()
    esc["history"].append({"ts": esc["updated_at"], "event": event, "by": by, "note": note})


def _reopen_escalation(esc: dict, note: str):
    esc.update(status="pending", assignee=None, resolution=None, delivered=False)
    esc.pop("resolution_note", None)
    _esc_event(esc, "reopened", "AI Support Agent", note)


def _esc_sort_key(e: dict):
    return ESC_STATUSES.index(e["status"]), e["priority"], e["id"]


@app.get("/api/admin/escalations")
def admin_escalations(status: str | None = None, priority: str | None = None,
                      role: str | None = None):
    items = [e for e in STATE.escalations
             if (not status or e["status"] == status)
             and (not priority or e["priority"] == priority)
             and (not role or e["source_role"] == role)]
    return sorted(items, key=_esc_sort_key)


@app.get("/api/admin/stats")
def admin_stats():
    items = STATE.escalations
    by_team: dict = {}
    for e in items:
        if e["status"] != "resolved":
            by_team[e["team"]] = by_team.get(e["team"], 0) + 1
    return {
        "total": len(items),
        **{s: sum(e["status"] == s for e in items) for s in ESC_STATUSES},
        "p1_open": sum(e["priority"] == "P1" and e["status"] != "resolved" for e in items),
        "open_by_team": by_team,
    }


@app.get("/api/admin/escalations/{esc_id}")
def get_escalation(esc_id: str):
    return _escalation(esc_id)


@app.post("/api/admin/escalations/{esc_id}/take")
def take_escalation(esc_id: str, body: TakeEscalation | None = None):
    body = body or TakeEscalation()
    esc = _escalation(esc_id)
    if esc["status"] != "pending":
        raise HTTPException(409, f"Тікет уже має статус «{esc['status']}»")
    esc["status"], esc["assignee"] = "in_progress", body.admin_name.strip()
    _esc_event(esc, "taken", esc["assignee"], "Взято в роботу")
    STATE.log("escalation_taken", esc_id=esc_id, by=esc["assignee"])
    return esc


@app.post("/api/admin/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: str, body: ResolveEscalation | None = None):
    body = body or ResolveEscalation()
    esc = _escalation(esc_id)
    if esc["status"] == "resolved":
        raise HTTPException(409, "Тікет уже вирішено")
    admin = body.admin_name.strip()
    default = DEFAULT_RESOLUTIONS["teacher"] if esc["source_role"] == "teacher" else \
        DEFAULT_RESOLUTIONS.get(esc["team"], DEFAULT_RESOLUTIONS["admin"])
    resolution = (body.resolution or "").strip() or default
    esc["status"], esc["resolution"] = "resolved", resolution
    esc["assignee"] = esc["assignee"] or admin
    esc["resolution_note"] = f"Вирішено адміністратором: {resolution}"
    if esc["source_role"] == "teacher":  # рішення по застарілому запису звільняє слот у календарі викладача
        STATE.calendar["stale_resolved"] = True
        STATE.calendar["stale_resolution_note"] = esc["resolution_note"]
    _esc_event(esc, "resolved", admin, resolution)
    STATE.log("escalation_resolved", esc_id=esc_id, by=admin)
    return esc


@app.post("/api/role-chat/updates")
def role_chat_updates(role: str):
    """Рішення адміністратора повертаються в історію чату користувача (один раз)."""
    fresh = [e for e in STATE.escalations
             if e["source_role"] == role and e["status"] == "resolved" and not e["delivered"]]
    for e in fresh:
        e["delivered"] = True
        _esc_event(e, "delivered", "AI Support Agent", "Результат повідомлено користувачу")
    return [{"id": e["id"], "problem": e["problem"], "resolution": e["resolution"],
             "assignee": e["assignee"]} for e in fresh]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

if not STATE.load():  # порожня БД (перший запуск) — наповнюємо демо-даними
    _seed()
    STATE.save()
