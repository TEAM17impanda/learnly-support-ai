"""REST API + роздача фронтенду."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

from . import agent, tools  # noqa: E402
from .context import build_context  # noqa: E402
from .data import COURSES, DEMO_MESSAGES, HISTORY  # noqa: E402
from .quality import score_reply  # noqa: E402
from .store import STATE, now  # noqa: E402

app = FastAPI(title="Learnly Support AI")
STATIC = Path(__file__).resolve().parent.parent / "static"
RETENTION_TOOLS = {"transfer_cohort", "extend_deadline", "book_mentor_session"}
MINUTES_PER_ACTION, MINUTES_PER_DRAFT = 4, 2  # оцінка ручної роботи, яку економить AI


# ---------------- моделі запитів ----------------
class NewTicket(BaseModel):
    student_id: str
    message: str = Field(min_length=1, max_length=2000)


class Message(BaseModel):
    role: str = "student"  # student | agent
    text: str = Field(min_length=1, max_length=2000)


class Reply(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    from_ai_draft: bool = False
    agent_name: str = "Агент"


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
    t["analysis"] = agent.analyze(s, message, t["messages"])
    t["actions"] = t["analysis"].pop("actions")
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
    return {"ok": True, "llm": bool(os.getenv("ANTHROPIC_API_KEY")), "autonomy": STATE.settings["autonomy"]}


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
    _msg(t, "agent", body.text.strip(), agent=body.agent_name, quality=q, from_ai_draft=body.from_ai_draft)
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
        if a.get("intent") == "refund" and t["actions"]:
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
        "time_saved_min": executed * MINUTES_PER_ACTION
                          + sum(1 for t in tickets if t["analysis"] and t["status"] != "open") * MINUTES_PER_DRAFT,
        "note": "Оцінка часу — модельна (4 хв/дія + 2 хв/чернетка) на мок-даних.",
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

_seed()
