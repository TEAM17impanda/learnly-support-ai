"""AI-агент: розуміє намір і справжню мету учня, пропонує дії та готує відповідь для агента підтримки.

Шлях 1: LLM (Anthropic) → JSON → валідація через tools.check().
Шлях 2: детермінований fallback на правилах (працює без ключа та інтернету).
Пріоритет і churn-risk рахуємо кодом — відтворювано.
"""
import json
import os
import re

from .context import build_context
from .policy import POLICY_TEXT
from .store import STATE
from .tools import PolicyError, TOOLS, check, tool_catalog

INTENTS = ["refund", "double_charge", "access", "deadline", "transfer", "certificate", "other"]
GOALS = ["needs_more_time", "disengaged_or_mismatch", "billing_error", "access_problem",
         "info", "unknown"]
SENTIMENTS = ["neutral", "negative", "angry"]

INTENT_PATTERNS = [
    ("double_charge", ["двічі", "списали двічі", "подвійн", "дубль", "charged twice", "двічі списан"]),
    ("refund", ["поверн", "refund", "верніть гроші", "повернути гроші"]),
    ("access", ["доступ", "не можу зайти", "не відкрива", "не пускає", "access", "увійти"]),
    ("certificate", ["сертифікат", "certificate", "диплом"]),
    ("deadline", ["дедлайн", "не встигаю", "продовж", "термін здач", "deadline"]),
    ("transfer", ["наступний потік", "інший потік", "перенес", "перейти на"]),
]
TIME_WORDS = ["не встиг", "немає часу", "нема часу", "навантаж", "зайнят", "багато роботи"]
MISMATCH_WORDS = ["не підходить", "не те", "не виправдав", "не подобається", "не моє", "складно"]
ANGRY_WORDS = ["жах", "обурен", "скарг", "шахра", "негайно", "безлад", "!!", "терміново"]
NEG_WORDS = ["погано", "розчарован", "проблем", "не працює", "не вийшло"]


def detect_intent(text: str) -> str:
    t = text.lower()
    for intent, words in INTENT_PATTERNS:
        if any(w in t for w in words):
            return intent
    return "other"


def detect_signals(text: str) -> dict:
    t = text.lower()
    return {
        "time_pressure": any(w in t for w in TIME_WORDS),
        "mismatch": any(w in t for w in MISMATCH_WORDS),
        "angry": any(w in t for w in ANGRY_WORDS),
        "negative": any(w in t for w in NEG_WORDS),
    }


def first_name(s: dict) -> str:
    return s["name"].split()[0]


def make_action(tool: str, args: dict, rationale: str, recommended: bool) -> dict:
    t = TOOLS[tool]
    return {
        "id": STATE.new_action_id(), "tool": tool, "title": t.title, "args": args,
        "risk": t.risk, "requires_approval": t.requires_approval,
        "rationale": rationale, "recommended": recommended,
        "status": "proposed", "result": None, "error": None, "executed_by": None,
    }


def compute_churn_risk(intent: str, ctx: dict, signals: dict, goal: str) -> int:
    risk = 15
    if intent == "refund":
        risk = 40 + ctx["gap"] * 6
        if goal == "disengaged_or_mismatch":
            risk += 15
    elif intent == "double_charge":
        risk = 50
    elif intent in ("access", "deadline"):
        risk = 25 + ctx["gap"] * 3
    if signals["angry"]:
        risk += 20
    elif signals["negative"]:
        risk += 8
    if ctx["last_login_days_ago"] >= 5:
        risk += 10
    if ctx["past_tickets"] >= 2:
        risk += 5
    return max(0, min(100, risk))


def compute_priority(intent: str, sentiment: str, churn: int, ctx: dict) -> dict:
    base = {"double_charge": 70, "access": 65, "refund": 60, "deadline": 40,
            "transfer": 35, "certificate": 25, "other": 30}[intent]
    score = base + (20 if sentiment == "angry" else 0) + (10 if churn >= 60 else 0)
    score += 5 if ctx["past_tickets"] >= 2 else 0
    label = "P1" if score >= 80 else "P2" if score >= 55 else "P3"
    return {"score": min(score, 100), "label": label}


# ======================= Rule-based fallback =======================
def heuristic_analyze(s: dict, message: str, history: list | None = None) -> dict:
    ctx = build_context(s)
    intent = detect_intent(message)
    sig = detect_signals(message)
    sentiment = "angry" if sig["angry"] else "negative" if sig["negative"] else "neutral"
    name = first_name(s)
    why: list[str] = []
    actions: list[dict] = []
    goal = "unknown"
    reply = ""

    def act(tool, args, rationale, rec):
        actions.append(make_action(tool, args, rationale, rec))

    if ctx["refunded"] and intent == "refund":
        why.append("Кошти за цей курс уже повернено раніше")
        reply = (f"Добрий день, {name}! Дякую за звернення. За цим курсом повернення вже оформлено — "
                 f"якщо у вас є додаткове питання, напишіть, будь ласка, деталі.")
        goal = "info"
    elif intent == "refund":
        days = ctx["days_since_payment"]
        pct = round(ctx["pace_ratio"] * 100)
        why.append(f"Запит на повернення коштів. Оплата була {days} дн. тому — вікно повернення "
                   f"{'відкрите' if ctx['refund_eligible'] else 'закрите'} (14 дн.)")
        why.append(f"Прогрес: {ctx['lessons_done']}/{ctx['lessons_expected']} уроків за планом "
                   f"({pct}%), відставання {ctx['gap']} ур., останній вхід {ctx['last_login_days_ago']} дн. тому")
        needs_time = sig["time_pressure"] or (ctx["pace_ratio"] >= 0.6 and not sig["mismatch"])
        if needs_time:
            goal = "needs_more_time"
            why.append("Темп близький до плану → проблема не в курсі, а в навантаженні. "
                       "Повернення можна замінити гнучкістю й зберегти учня")
            if ctx["can_transfer"]:
                act("transfer_cohort", {"target_cohort": ctx["next_cohort"]},
                    f"Перенос на потік {ctx['next_cohort']} знімає тиск дедлайнів і зберігає "
                    f"{ctx['amount_paid']} грн", True)
                if ctx["can_extend"]:
                    act("extend_deadline", {"days": 7},
                        "Альтернатива: більше часу на поточному потоці", False)
            elif ctx["can_extend"]:
                act("extend_deadline", {"days": 7}, "Додатковий час замість повернення", True)
            if ctx["refund_eligible"]:
                act("request_refund", {}, "Запасний варіант, якщо учень відмовиться від пропозиції", False)
            reply = (f"Добрий день, {name}! Розумію, що зараз складно вкласти навчання у свій графік. "
                     f"Ви вже пройшли {ctx['lessons_done']} з {ctx['lessons_total']} уроків — це хороший старт. "
                     f"Пропоную не повертати кошти, а перенести вас на наступний потік ({ctx['next_cohort']}) "
                     f"без доплат — тоді навчання піде у комфортному темпі. Якщо хочете, зробимо це сьогодні; "
                     f"якщо ні — оформимо повернення.")
        else:
            goal = "disengaged_or_mismatch"
            if ctx["refund_eligible"]:
                why.append(f"Учень майже не залучений ({pct}% від плану), курс не підійшов → "
                           f"повернення обґрунтоване ({ctx['refund_pct']}% за політикою)")
                act("request_refund", {}, f"У вікні 14 днів, пройдено {int(ctx['progress_total']*100)}% "
                    f"курсу → повернення {ctx['refund_pct']}%", True)
                act("book_mentor_session", {}, "Утримання: безкоштовна сесія з ментором, "
                    "якщо учень готовий дати курсу шанс", False)
                reply = (f"Добрий день, {name}! Дякую, що написали. Шкода, що курс не підійшов. "
                         f"Ви в межах 14 днів, тому ми можемо оформити повернення "
                         f"({ctx['refund_pct']}% суми) вже сьогодні. Якщо захочете дати курсу ще шанс, "
                         f"можу запропонувати безкоштовну сесію з ментором — скажіть, що вам зручніше.")
            else:
                why.append("Вікно повернення закрите — автоматичне повернення неможливе за політикою")
                if ctx["can_extend"]:
                    act("extend_deadline", {"days": 7}, "Допомогти наздогнати програму", False)
                act("escalate_to_human", {"team": "billing",
                    "reason": "Запит на повернення поза вікном 14 днів, потрібне виняткове рішення"},
                    "Виняток із політики може ухвалити лише людина", True)
                reply = (f"Добрий день, {name}! Розумію ваше розчарування. На жаль, з моменту оплати "
                         f"минуло {days} дн., тож автоматичне повернення недоступне (діє вікно 14 днів). "
                         f"Я передав ваш запит команді billing на розгляд — відповідь буде протягом "
                         f"одного робочого дня. Тим часом можу продовжити дедлайн, щоб вам було легше наздогнати.")
    elif intent == "double_charge":
        goal = "billing_error"
        if ctx["duplicate_ids"]:
            why.append(f"Знайдено дубльоване списання: {ctx['duplicate_amount']} грн (платежі "
                       f"{', '.join(ctx['duplicate_ids'])}) — помилка білінгу")
            act("refund_duplicate_charge", {}, f"Повернути зайві {ctx['duplicate_amount']} грн",
                True)
            reply = (f"Добрий день, {name}! Дуже перепрошую за незручності. Я перевірив оплати: "
                     f"справді було два однакові списання. Оформлюю повернення зайвих "
                     f"{ctx['duplicate_amount']} грн — кошти повернуться на картку протягом 3–5 робочих днів. "
                     f"Доступ до курсу залишається без змін.")
        else:
            why.append("Скарга на подвійне списання, але дублів в оплатах не знайдено")
            act("escalate_to_human", {"team": "billing", "reason": "Скарга на подвійне списання, "
                "дублів у системі немає — потрібна перевірка з банком"}, "Потрібна ручна перевірка", True)
            reply = (f"Добрий день, {name}! Перепрошую за незручності. У нашій системі я бачу лише "
                     f"одне списання, тому передаю запит команді billing для звірки з банком. "
                     f"Надішліть, будь ласка, скрін виписки, щоб прискорити перевірку.")
    elif intent == "access":
        goal = "access_problem"
        if ctx["has_paid"] and not ctx["access_active"] and not ctx["refunded"]:
            why.append(f"Оплата підтверджена ({ctx['days_since_payment']} дн. тому), але доступ "
                       f"деактивовано — ймовірний збій синхронізації")
            act("grant_access", {}, "Оплата є, доступ неактивний → безпечно відновити", True)
            reply = (f"Добрий день, {name}! Дякую за повідомлення, розумію, як це неприємно. "
                     f"Я перевірив: оплата пройшла, але доступ не активувався через технічний збій. "
                     f"Я вже відновив доступ — спробуйте, будь ласка, зайти ще раз. "
                     f"Якщо не вийде, напишіть мені — розберемося.")
        elif not ctx["has_paid"]:
            why.append("Успішної оплати не знайдено")
            act("escalate_to_human", {"team": "billing", "reason": "Немає оплати, учень скаржиться на доступ"},
                "Потрібна перевірка оплати", True)
            reply = (f"Добрий день, {name}! Я не бачу успішної оплати у системі, тож передаю "
                     f"запит команді billing. Надішліть, будь ласка, чек або скрін оплати.")
        else:
            why.append("Доступ активний — ймовірно, проблема на стороні браузера/акаунта")
            reply = (f"Добрий день, {name}! З мого боку доступ активний. Спробуйте, будь ласка, "
                     f"вийти й увійти знову та відкрити курс в іншому браузері. "
                     f"Якщо не допоможе — надішліть скрін помилки, і я передам технічній команді.")
    elif intent == "certificate":
        goal = "info"
        if ctx["certificate_ready"]:
            why.append(f"Пройдено {ctx['lessons_done']}/{ctx['lessons_total']} уроків → сертифікат належить")
            act("issue_certificate", {}, "Всі уроки пройдено", True)
            reply = (f"Вітаю, {name}, із завершенням курсу! Дякую за вашу роботу. Я вже оформив "
                     f"сертифікат — він надійде на email протягом кількох хвилин.")
        elif ctx["certificate_issued"]:
            why.append("Сертифікат уже видано раніше")
            reply = f"Добрий день, {name}! Сертифікат уже надіслано на вашу пошту — перевірте, будь ласка, папку «Спам»."
        else:
            why.append(f"Пройдено лише {ctx['lessons_done']}/{ctx['lessons_total']} уроків")
            reply = (f"Добрий день, {name}! Для сертифіката потрібно пройти всі уроки: "
                     f"вам лишилось {ctx['lessons_left']}. Після завершення я одразу його оформлю.")
    elif intent == "deadline":
        goal = "needs_more_time"
        if ctx["can_extend"]:
            why.append(f"Просить більше часу; продовжень використано {ctx['extensions_used']}/2")
            act("extend_deadline", {"days": 5}, "Ліміт продовжень не вичерпано", True)
            reply = (f"Добрий день, {name}! Розумію, що буває складно. Я продовжу дедлайн на 5 днів — "
                     f"наступний крок: здати завдання до нового терміну.")
        else:
            why.append("Ліміт продовжень вичерпано")
            act("escalate_to_human", {"team": "curator", "reason": "Ліміт продовжень вичерпано"},
                "Потрібне рішення куратора", True)
            reply = (f"Добрий день, {name}! Розумію вас. Ліміт продовжень уже використано, "
                     f"тож я передав питання куратору — він відповість протягом дня.")
    elif intent == "transfer":
        goal = "needs_more_time"
        if ctx["can_transfer"]:
            why.append(f"Перенос доступний (прогрес {int(ctx['progress_total']*100)}% ≤ 50%)")
            act("transfer_cohort", {"target_cohort": ctx["next_cohort"]}, "Умови переносу виконано", True)
            reply = (f"Добрий день, {name}! Без проблем — можу перенести вас на потік "
                     f"{ctx['next_cohort']}. Підтвердіть, і я оформлю це сьогодні.")
        else:
            why.append("Перенос недоступний за політикою")
            act("escalate_to_human", {"team": "curator", "reason": "Перенос потоку поза політикою"},
                "Потрібне рішення куратора", True)
            reply = (f"Добрий день, {name}! Розумію. Автоматичний перенос недоступний за умовами, "
                     f"тому передаю питання куратору — він запропонує варіанти.")
    else:
        why.append("Намір неочевидний — потрібне уточнення, дій без підтвердження суті не пропонуємо")
        act("escalate_to_human", {"team": "curator", "reason": "Не вдалося визначити запит"},
            "Низька впевненість у наміру", False)
        reply = (f"Добрий день, {name}! Дякую за повідомлення. Щоб допомогти швидше, уточніть, будь ласка, "
                 f"що саме сталося і з яким курсом.")

    churn = compute_churn_risk(intent, ctx, sig, goal)
    return {
        "intent": intent, "true_goal": goal, "sentiment": sentiment, "churn_risk": churn,
        "priority": compute_priority(intent, sentiment, churn, ctx),
        "reasoning": why, "suggested_reply": reply, "actions": actions,
        "context": ctx, "source": "rules",
    }


# ======================= LLM-шлях =======================
SYSTEM_PROMPT = """Ти — операційний AI-асистент підтримки онлайн-школи Learnly. Допомагаєш агенту підтримки.
Завдання: визначити намір учня та його СПРАВЖНЮ МЕТУ (вона може відрізнятись від сказаного), запропонувати дії з каталогу та написати чернетку відповіді українською.
Правила:
- Спирайся ТІЛЬКИ на наданий контекст і політику. Нічого не вигадуй.
- Якщо учень просить повернення, але його темп навчання хороший або він скаржиться на брак часу — спершу пропонуй утримання (перенос потоку / продовження дедлайну), повернення — запасною дією.
- Не пропонуй дію, яка порушує політику. Якщо даних бракує — став уточнююче питання і actions: [].
- reasoning: 2-4 короткі пункти з конкретними числами з контексту.
- Відповідь учню: ввічливо, з іменем, емпатією і конкретним наступним кроком.
Поверни ТІЛЬКИ валідний JSON без пояснень."""

JSON_SCHEMA_HINT = {
    "intent": "|".join(INTENTS), "true_goal": "|".join(GOALS), "sentiment": "|".join(SENTIMENTS),
    "reasoning": ["..."], "reply": "...",
    "actions": [{"tool": "назва з каталогу", "args": {}, "rationale": "...", "recommended": True}],
}


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("JSON не знайдено у відповіді LLM")
    return json.loads(m.group(0))


def llm_analyze(s: dict, message: str, history: list | None = None) -> dict:
    import anthropic  # імпорт тут, щоб fallback працював і без пакета

    ctx = build_context(s)
    client = anthropic.Anthropic(timeout=25.0)
    payload = {
        "student": {"name": s["name"]}, "message": message,
        "chat_history": [{"role": m["role"], "text": m["text"]} for m in (history or [])][-6:],
        "context": ctx, "policy": POLICY_TEXT, "tools": tool_catalog(),
        "response_schema": JSON_SCHEMA_HINT,
    }
    resp = client.messages.create(
        model=os.getenv("LLM_MODEL", "claude-sonnet-5-5"), max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    data = _extract_json("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))

    intent = data.get("intent") if data.get("intent") in INTENTS else detect_intent(message)
    goal = data.get("true_goal") if data.get("true_goal") in GOALS else "unknown"
    sentiment = data.get("sentiment") if data.get("sentiment") in SENTIMENTS else "neutral"

    actions = []
    for a in data.get("actions", []):
        tool, args = a.get("tool"), a.get("args") or {}
        if tool not in TOOLS or not isinstance(args, dict):
            continue
        try:
            check(s, tool, args)  # policy-guard: відкидаємо дії, що порушують правила
        except PolicyError:
            continue
        actions.append(make_action(tool, args, str(a.get("rationale", "")), bool(a.get("recommended"))))
    reply = str(data.get("reply", "")).strip()
    if not actions or not reply:
        raise ValueError("LLM не повернув валідних дій/відповіді")

    sig = detect_signals(message)
    churn = compute_churn_risk(intent, ctx, sig, goal)
    return {
        "intent": intent, "true_goal": goal, "sentiment": sentiment, "churn_risk": churn,
        "priority": compute_priority(intent, sentiment, churn, ctx),
        "reasoning": [str(x) for x in data.get("reasoning", [])][:5],
        "suggested_reply": reply, "actions": actions, "context": ctx, "source": "llm",
    }


def analyze(s: dict, message: str, history: list | None = None) -> dict:
    """Головна точка входу: LLM, якщо доступний, інакше (або при збої) — правила."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return llm_analyze(s, message, history)
        except Exception as e:  # будь-який збій LLM не має ламати підтримку
            result = heuristic_analyze(s, message, history)
            result["llm_error"] = f"{type(e).__name__}: {e}"[:200]
            return result
    return heuristic_analyze(s, message, history)
