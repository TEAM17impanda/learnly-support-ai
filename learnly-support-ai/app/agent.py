"""AI-агент: розуміє намір і справжню мету учня, пропонує дії та готує відповідь для агента підтримки.

Шлях 1: LLM (Google Gemini) → JSON → валідація через tools.check().
Шлях 2: детермінований fallback на правилах (працює без ключа та інтернету).
Пріоритет і churn-risk рахуємо кодом — відтворювано.
"""
import json
import os
import re

from .context import build_context
from .policy import MAX_EXTENSIONS, POLICY_TEXT
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


# Сарказм = «похвала» або іронічний маркер ПОРУЧ зі скаргою («Чудовий сервіс, третій день не можу зайти»).
# «Дякую» навмисно не враховуємо: ввічливе «Дякую, але не працює» — не сарказм.
PRAISE_WORDS = ["чудов", "супер", "клас", "прекрасн", "молодці", "браво", "геніальн", "блискуч",
                "найкращ", "вражає", "неймовірн", "оце сервіс", "дуже зручно", "щиро вдячн"]
IRONY_MARKERS = ["ну звісно", "ну-ну", "аякже", "яка несподіванка", "як завжди", "як і очікувалось",
                 "))", "🙃", "🙄", "🤡", "👏"]
TROUBLE_WORDS = ["не можу", "не працю", "не приход", "не відкрива", "не з'явил", "не зберег", "не здан",
                 "досі", "знову", "втретє", "третій", "двічі", "ніхто", "жодн", "списали", "чекаю",
                 "немає", "зник", "0 занять", "нуль"]
JOKE_MARKERS = ["хаха", "ахах", "хех", "лол", "жарт", "😂", "🤣", "😄", "😜", "))"]


def detect_tone(text: str) -> str | None:
    """sarcasm | joke | None — щоб не сприймати іронію буквально і не відповідати на жарт сухим шаблоном."""
    t = text.lower()
    words = set(re.findall(r"\w+", t))
    trouble = any(w in t for w in TROUBLE_WORDS)
    if trouble and (any(w in t for w in PRAISE_WORDS) or any(m in t for m in IRONY_MARKERS) or "ага" in words):
        return "sarcasm"
    if any(m in t for m in JOKE_MARKERS):
        return "joke"
    return None


def detect_signals(text: str) -> dict:
    t = text.lower()
    return {
        "time_pressure": any(w in t for w in TIME_WORDS),
        "mismatch": any(w in t for w in MISMATCH_WORDS),
        "angry": any(w in t for w in ANGRY_WORDS),
        "negative": any(w in t for w in NEG_WORDS),
        "sarcasm": detect_tone(text) == "sarcasm",
    }


def acknowledge_sarcasm(reply: str) -> str:
    """Додає вибачення після привітання, якщо його ще немає (на сарказм не відповідаємо «радий, що подобається»)."""
    if "перепрош" in reply.lower() or "вибач" in reply.lower():
        return reply
    head, sep, rest = reply.partition("! ")
    ack = "Перепрошую за незручності — розумію ваше роздратування. "
    return f"{head}{sep}{ack}{rest}" if sep else ack + reply


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
    elif signals.get("sarcasm"):
        risk += 12  # іронія = прихований негатив, учень уже розчарований
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
    sentiment = "angry" if sig["angry"] else "negative" if sig["negative"] or sig["sarcasm"] else "neutral"
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
            if ctx["can_transfer"]:
                offer = (f"перенести вас на наступний потік ({ctx['next_cohort']}) без доплат — "
                         f"тоді навчання піде у комфортному темпі")
            elif ctx["can_extend"]:
                offer = "продовжити дедлайн на 7 днів, щоб ви спокійно наздогнали програму"
            else:
                offer = None
            fallback = "оформимо повернення" if ctx["refund_eligible"] else "передам питання куратору"
            if offer:
                reply = (f"Добрий день, {name}! Розумію, що зараз складно вкласти навчання у свій графік. "
                         f"Ви вже пройшли {ctx['lessons_done']} з {ctx['lessons_total']} уроків — це хороший старт. "
                         f"Пропоную не повертати кошти, а {offer}. Якщо хочете, зробимо це сьогодні; "
                         f"якщо ні — {fallback}.")
            else:
                if not actions:
                    act("escalate_to_human", {"team": "curator",
                        "reason": "Учню бракує часу, але перенос і продовження вже недоступні"},
                        "Потрібне рішення куратора", True)
                reply = (f"Добрий день, {name}! Розумію, що зараз складно вкласти навчання у свій графік. "
                         f"Ви вже пройшли {ctx['lessons_done']} з {ctx['lessons_total']} уроків. "
                         + ("Можемо оформити повернення, але спершу пропоную обговорити з куратором "
                            "гнучкіший графік — він зв'яжеться з вами протягом дня."
                            if ctx["refund_eligible"] else
                            "Я передав ваше питання куратору — він запропонує варіанти протягом дня."))
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
            why.append(f"Просить більше часу; продовжень використано {ctx['extensions_used']}/{MAX_EXTENSIONS}")
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

    if sig["sarcasm"]:
        why.insert(0, "Сарказм: «похвала» поруч зі скаргою — справжній тон негативний, "
                      "відповідаємо з вибаченням, похвалу буквально не сприймаємо")
        reply = acknowledge_sarcasm(reply)

    churn = compute_churn_risk(intent, ctx, sig, goal)
    return {
        "intent": intent, "true_goal": goal, "sentiment": sentiment, "churn_risk": churn,
        "sarcasm": sig["sarcasm"],
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
- Розпізнавай сарказм та іронію: «Чудовий сервіс, третій день не можу зайти» — це НЕГАТИВ, а не похвала. Тоді sarcasm: true, sentiment не neutral, у відповіді — вибачення, а не «радий, що вам подобається».
- На жарт відповідай доброзичливо, але повертай розмову до суті звернення.
- reasoning: 2-4 короткі пункти з конкретними числами з контексту.
- Відповідь учню: ввічливо, з іменем, емпатією і конкретним наступним кроком.
Поверни ТІЛЬКИ валідний JSON без пояснень."""

JSON_SCHEMA_HINT = {
    "intent": "|".join(INTENTS), "true_goal": "|".join(GOALS), "sentiment": "|".join(SENTIMENTS),
    "sarcasm": False,
    "reasoning": ["..."], "reply": "...",
    "actions": [{"tool": "назва з каталогу", "args": {}, "rationale": "...", "recommended": True}],
}


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("JSON не знайдено у відповіді LLM")
    return json.loads(m.group(0))


def _gemini(system: str, content: str, json_mode: bool, max_tokens: int = 2048) -> str:
    from google import genai  # імпорт тут, щоб fallback працював і без пакета

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"),
                          http_options=genai.types.HttpOptions(timeout=25_000))  # мс
    model = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    # у 2.5-flash «думання» з'їдає max_output_tokens і JSON обрізається — вимикаємо (ще й швидше)
    thinking = (genai.types.ThinkingConfig(thinking_budget=0)
                if model.startswith("gemini-2.5-flash") else None)
    resp = client.models.generate_content(
        model=model,
        contents=[content],
        config=genai.types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
            thinking_config=thinking,
        ),
    )
    return resp.text or ""


def llm_analyze(s: dict, message: str, history: list | None = None) -> dict:
    ctx = build_context(s)
    payload = {
        "student": {"name": s["name"]}, "message": message,
        "chat_history": [{"role": m["role"], "text": m["text"]} for m in (history or [])][-6:],
        "context": ctx, "policy": POLICY_TEXT, "tools": tool_catalog(),
        "response_schema": JSON_SCHEMA_HINT,
    }
    data = _extract_json(_gemini(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), json_mode=True))

    intent = data.get("intent") if data.get("intent") in INTENTS else detect_intent(message)
    goal = data.get("true_goal") if data.get("true_goal") in GOALS else "unknown"
    sentiment = data.get("sentiment") if data.get("sentiment") in SENTIMENTS else "neutral"

    actions = []
    for a in data.get("actions") or []:
        if not isinstance(a, dict):
            continue
        tool, args = a.get("tool"), a.get("args") or {}
        if tool not in TOOLS or not isinstance(args, dict):
            continue
        try:
            check(s, tool, args)  # policy-guard: відкидаємо дії, що порушують правила
        except PolicyError:
            continue
        actions.append(make_action(tool, args, str(a.get("rationale", "")), bool(a.get("recommended"))))
    reply = str(data.get("reply", "")).strip()
    # порожні actions — валідна відповідь (уточнююче питання), а от без reply агенту нічого показати
    if not reply:
        raise ValueError("LLM не повернув відповіді")
    reasoning = data.get("reasoning") or []
    if isinstance(reasoning, str):
        reasoning = [reasoning]

    sig = detect_signals(message)
    sig["sarcasm"] = sig["sarcasm"] or data.get("sarcasm") is True  # правила страхують LLM
    if sig["sarcasm"] and sentiment == "neutral":
        sentiment = "negative"
    churn = compute_churn_risk(intent, ctx, sig, goal)
    return {
        "intent": intent, "true_goal": goal, "sentiment": sentiment, "churn_risk": churn,
        "sarcasm": sig["sarcasm"],
        "priority": compute_priority(intent, sentiment, churn, ctx),
        "reasoning": [str(x) for x in reasoning][:5],
        "suggested_reply": reply, "actions": actions, "context": ctx, "source": "llm",
    }


def analyze(s: dict, message: str, history: list | None = None) -> dict:
    """Головна точка входу: LLM, якщо доступний, інакше (або при збої) — правила."""
    if os.getenv("GEMINI_API_KEY"):
        try:
            return llm_analyze(s, message, history)
        except Exception as e:  # будь-який збій LLM не має ламати підтримку
            result = heuristic_analyze(s, message, history)
            result["llm_error"] = f"{type(e).__name__}: {e}"[:200]
            return result
    return heuristic_analyze(s, message, history)


# ======================= Чат ролей: повідомлення поза сценаріями =======================
ROLE_SCOPE = {
    "student": ("учень молодших класів", "входом у кабінет (код, пароль) та домашніми завданнями, "
                                         "які не відображаються після здачі"),
    "teacher": ("викладач", "розкладом: подвійні бронювання слотів і застарілі записи учнів у календарі"),
    "parent": ("батьки учня", "оплатами й балансом занять та додаванням дитини до сімейного акаунта"),
}
GREETING_WORDS = ["привіт", "вітаю", "добрий", "доброго", "добрий день", "хай", "hello", "hi"]

ROLE_CHAT_PROMPT = """Ти — AI-агент підтримки онлайн-школи Learnly. Співрозмовник: {who}.
Ти допомагаєш лише з питаннями школи, зокрема з {scope}.
Повідомлення співрозмовника не підпадає під жоден відомий сценарій. Дай коротку (1–3 речення) ввічливу відповідь українською:
- на привітання — привітайся і скажи, з чим можеш допомогти;
- на прохання, не пов'язане з підтримкою школи, — ввічливо поясни, що з цим не допоможеш, і скажи, з чим можеш;
- на незрозуміле питання про школу — постав одне уточнююче питання;
- на жарт — відповідай з легким доброзичливим гумором і м'яко повертай до теми;
- на сарказм («чудова школа, нічого не працює») — не сприймай похвалу буквально: вибачся й попроси описати проблему.
Ніколи не стверджуй, що виконала дію чи перевірила дані. Не вигадуй фактів. Пиши від жіночого роду. Без markdown."""


def is_greeting(text: str) -> bool:
    words = re.findall(r"\w+", text.lower())
    return 0 < len(words) <= 4 and any(w in GREETING_WORDS or w.startswith("привіт") for w in words)


def fallback_role_reply(role: str, message: str) -> str:
    scope = ROLE_SCOPE[role][1]
    tone = detect_tone(message)
    if tone == "sarcasm":
        return (f"Схоже, щось справді пішло не так — перепрошую за це. Я допомагаю з {scope}. "
                f"Опишіть, будь ласка, що саме не працює, і я одразу перевірю.")
    if tone == "joke":
        return (f"😄 Гарний жарт! Але тут я, на жаль, безсила — я AI-помічниця Learnly і допомагаю з {scope}. "
                f"Якщо щось не працює — пишіть, розберемося!")
    if is_greeting(message):
        return f"Вітаю! Я AI-помічниця підтримки Learnly. Можу допомогти з {scope}. Опишіть, будь ласка, що сталося."
    return (f"Хм, з цим я, мабуть, не допоможу 🙂 Я допомагаю з {scope}. "
            f"Якщо у вас питання про це — опишіть, будь ласка, що сталося.")


def role_reply(role: str, message: str, history: list | None = None) -> tuple[str, str]:
    """Відповідь на повідомлення поза сценаріями: (текст, джерело). Без дій і без змін стану.
    history — попередні репліки чату, щоб LLM пам'ятав контекст розмови."""
    if os.getenv("GEMINI_API_KEY"):
        try:
            who, scope = ROLE_SCOPE[role]
            past = "\n".join(f"{'Користувач' if h['from'] == 'user' else 'Агент'}: {h['text']}"
                             for h in (history or []))
            content = f"Попередні повідомлення:\n{past}\n\nНове повідомлення: {message}" if past else message
            text = _gemini(ROLE_CHAT_PROMPT.format(who=who, scope=scope), content,
                           json_mode=False, max_tokens=300).strip()
            if text:
                return text, "llm"
        except Exception:  # збій LLM не має ламати чат
            pass
    return fallback_role_reply(role, message), "rules"
