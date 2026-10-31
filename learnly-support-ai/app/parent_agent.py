"""Parent AI-агент: логіка підтримки батьків.

Сценарій 1: Оплата пройшла, але заняття не з'явилися
  - Витягує акаунт батьків через STATE (MCP-like data access)
  - Шукає неприв'язані платежі
  - Знаходить платіж з одруківкою в email → готує ескалацію на finance
  - Якщо не знайдено — запитує email/картку (multi-turn clarification)

Сценарій 2: Додавання дитини до сімейного акаунта
  - Перевіряє існуючих дітей на акаунті
  - Ескалює на admin для ручної валідації
  - Повідомляє про статус і наступні кроки

Guardrails: AI не проводить фінансових операцій (link_payment — тільки admin).
"""
import difflib
import re
from datetime import datetime

from .store import STATE, now

# ============================================================
# Константи та словники
# ============================================================

PARENT_INTENTS = ["payment_missing", "sibling_add", "other"]

PAYMENT_KEYWORDS = [
    "оплат", "сплат", "баланс", "списал", "списан", "2400", "2,400", "платіж",
    "гроші", "заплатил", "оплата пройшла", "гроші списали", "заняття не з'явил",
    "заняття не нарахувал", "payment", "paid",
]

SIBLING_KEYWORDS = [
    "дитин", "доньк", "дочк", "сина", "профіль дитини", "сімейн",
    "другу дитину", "ще одну дитину", "брат", "сестр", "додат",
    "додати дитину", "add child",
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CARD_RE = re.compile(r"(?:карт\w*|цифр\w*)\D{0,25}(\d{4})\b|^\s*\*?(\d{4})\s*$")

# Простий шаблон для вилучення імені дитини з повідомлення
_CHILD_NAME_RE = re.compile(
    r"(?:дочк[иу]?|доньк[иу]?|сина?|дитин[иу]?|профіль)\s+([А-ЯЇІЄА-яїієa-zA-Z][а-яїієa-z]+)",
    re.IGNORECASE | re.UNICODE,
)
_CHILD_NAME_BRACKET_RE = re.compile(r"\(([А-ЯЇІЄА-яїієa-zA-Z][а-яїієa-z]+)[,\s]")


def detect_parent_intent(message: str) -> str:
    """Визначає намір батьків за текстом повідомлення.

    Returns:
        "payment_missing" | "sibling_add" | "other"
    """
    t = message.lower()
    if any(kw in t for kw in PAYMENT_KEYWORDS):
        return "payment_missing"
    if any(kw in t for kw in SIBLING_KEYWORDS):
        return "sibling_add"
    return "other"


def _extract_child_name(message: str) -> str | None:
    """Намагається вилучити ім'я дитини з тексту повідомлення."""
    m = _CHILD_NAME_BRACKET_RE.search(message)
    if m:
        return m.group(1)
    m = _CHILD_NAME_RE.search(message)
    if m:
        return m.group(1)
    return None


# ============================================================
# Аналіз сценарію 1: Оплата пройшла, заняття не з'явилися
# ============================================================

def analyze_payment_missing(message: str, account: dict, school_data: dict) -> dict:
    """Аналізує ситуацію з оплатою, яка не прив'язалась до акаунта.

    Аргументи:
        message     — оригінальне повідомлення батьків
        account     — dict акаунту (з STATE.school["accounts"])
        school_data — dict з ключем "payments" (список всіх платежів)

    Повертає структурований dict для main.py, який сам виконує MCP-дії.
    """
    acc_email = account.get("email", "")
    acc_balance = account.get("lessons_balance", 0)
    acc_name = account.get("name", "")

    checks_performed = [
        f"Перевірено акаунт батьків: {acc_email}, баланс {acc_balance} занять",
    ]

    # Шукаємо всі платежі — прив'язані та неприв'язані
    all_payments = school_data.get("payments", [])
    linked_on_account = [
        p for p in all_payments
        if p.get("linked_account") == account.get("id")
    ]
    unlinked_all = [p for p in all_payments if not p.get("linked_account")]

    checks_performed.append(
        f"Знайдено платежів на акаунті: {len(linked_on_account)}, "
        f"неприв'язаних у системі: {len(unlinked_all)}"
    )

    # Визначаємо: чи є email або картка в повідомленні
    email_match = EMAIL_RE.search(message)
    card_match = CARD_RE.search(message.lower())

    provided_email = email_match.group(0) if email_match else None
    provided_card = (card_match.group(1) or card_match.group(2)) if card_match else None

    # --- Пошук за наданими даними ---
    if provided_email or provided_card:
        candidates = []
        for p in unlinked_all:
            if provided_email and p.get("payer_email", "").lower() == provided_email.lower():
                candidates.append(p)
            elif provided_card and p.get("card_last4") == provided_card:
                candidates.append(p)

        checks_performed.append(
            f"Пошук за наданими даними ({'email' if provided_email else 'картка'}): "
            f"знайдено {len(candidates)} неприв'язаних платежів"
        )

        if candidates:
            pay = candidates[0]
            similar = difflib.SequenceMatcher(None, pay["payer_email"], acc_email).ratio() > 0.75
            why = (f"на пошту {pay['payer_email']} замість {acc_email} — схоже на одруківку"
                   if similar else f"на іншу пошту ({pay['payer_email']})")
            checks_performed.append(f"Схожість email з акаунтом: {similar} → {why}")

            return {
                "intent": "payment_missing",
                "intent_title": "Оплата пройшла, заняття не з'явилися",
                "status": "payment_found",
                "verified_context": {
                    "account_email": acc_email,
                    "account_balance": acc_balance,
                    "payment_id": pay["id"],
                    "payment_amount": pay.get("amount"),
                    "payment_package": pay.get("package"),
                    "payment_email": pay.get("payer_email"),
                    "payment_card_last4": pay.get("card_last4"),
                    "payment_paid_at": pay.get("paid_at"),
                    "email_typo": similar,
                    "why": why,
                },
                "checks_performed": checks_performed,
                "decision_type": "escalate_to_finance",
                "escalation_reason": (
                    "Фінансова операція (прив'язка платежу й нарахування занять): "
                    "MCP-шлюз дозволяє її лише адміністратору"
                ),
                "priority": "P1",
                "proposed_fix": {
                    "tool": "link_payment",
                    "args": {"payment_id": pay["id"], "account_id": account.get("id")},
                    "title": (f"Прив'язати {pay['id']} до акаунта {acc_email} "
                              f"і зарахувати {pay.get('package', 'пакет')}"),
                },
                "payment": pay,
                "account": account,
                "original_message": message,
                "ai_reply": (
                    f"Знайшла! Оплата {pay.get('amount')} грн ({pay.get('package')}, {pay.get('paid_at')}) "
                    f"пройшла {why}, тому вона не прив'язалася до вашого акаунта. "
                    "Фінансові зміни я не можу робити самостійно, "
                    f"тож передам адміністратору терміновий тікет із готовим рішенням — прив'язати оплату "
                    "до вашого акаунта. Щойно він підтвердить, заняття з'являться на балансі, і я вам напишу."
                ),
                "guardrails": [
                    "AI не виконує фінансових операцій — тільки адміністратор може прив'язати платіж",
                    "link_payment доступний лише ролі admin у MCP-шлюзі",
                    "Зарахування занять відбувається лише після підтвердження адміністратором",
                ],
                "timestamp": now(),
            }
        else:
            # Дані надані, але платіж не знайдено
            checks_performed.append("Неприв'язаних оплат за наданими даними не знайдено")
            return {
                "intent": "payment_missing",
                "intent_title": "Оплата пройшла, заняття не з'явилися",
                "status": "not_found",
                "verified_context": {
                    "account_email": acc_email,
                    "account_balance": acc_balance,
                    "searched_email": provided_email,
                    "searched_card": provided_card,
                },
                "checks_performed": checks_performed,
                "decision_type": "escalate_to_finance",
                "escalation_reason": "Потрібна ручна звірка з банком — платіж не знайдено за наданими даними",
                "priority": "P1",
                "proposed_fix": None,
                "payment": None,
                "account": account,
                "original_message": message,
                "ai_reply": (
                    "За цими даними неприв'язаної оплати я не знайшла. "
                    "Передам запит фінансовому відділу — вони звірять платіж із банком. "
                    "Якщо є квитанція, надішліть її, будь ласка."
                ),
                "guardrails": [
                    "AI не виконує фінансових операцій без підтвердження адміністратора",
                ],
                "timestamp": now(),
            }

    # --- Автоматичний пошук неприв'язаних платежів за email акаунта ---
    unlinked_on_account_email = [
        p for p in unlinked_all
        if p.get("payer_email", "").lower() == acc_email.lower()
    ]

    if unlinked_on_account_email:
        pay = unlinked_on_account_email[0]
        checks_performed.append(f"Знайдено неприв'язаний платіж {pay['id']} на email акаунта")
        return {
            "intent": "payment_missing",
            "intent_title": "Оплата пройшла, заняття не з'явилися",
            "status": "payment_found",
            "verified_context": {
                "account_email": acc_email,
                "account_balance": acc_balance,
                "payment_id": pay["id"],
                "payment_amount": pay.get("amount"),
                "payment_package": pay.get("package"),
                "payment_email": pay.get("payer_email"),
                "payment_card_last4": pay.get("card_last4"),
                "payment_paid_at": pay.get("paid_at"),
                "email_typo": False,
                "why": "на ту саму пошту, але оплата не прив'язалася (технічна проблема)",
            },
            "checks_performed": checks_performed,
            "decision_type": "escalate_to_finance",
            "escalation_reason": (
                "Фінансова операція (прив'язка платежу): MCP-шлюз дозволяє лише адміністратору"
            ),
            "priority": "P1",
            "proposed_fix": {
                "tool": "link_payment",
                "args": {"payment_id": pay["id"], "account_id": account.get("id")},
                "title": f"Прив'язати {pay['id']} до акаунта {acc_email} і зарахувати {pay.get('package', 'пакет')}",
            },
            "payment": pay,
            "account": account,
            "original_message": message,
            "ai_reply": (
                f"Перевірила ваш акаунт ({acc_email}): знайшла оплату {pay.get('amount')} грн "
                f"({pay.get('package')}, {pay.get('paid_at')}), яка з технічних причин не прив'язалась до балансу. "
                "Передам адміністратору тікет із готовим рішенням — зараховати заняття на ваш акаунт."
            ),
            "guardrails": [
                "AI не виконує фінансових операцій — тільки адміністратор може прив'язати платіж",
                "link_payment доступний лише ролі admin у MCP-шлюзі",
            ],
            "timestamp": now(),
        }

    # --- Шукаємо серед усіх неприв'язаних (різні email — одруківка) ---
    similar_unlinked = []
    for p in unlinked_all:
        ratio = difflib.SequenceMatcher(None, p.get("payer_email", ""), acc_email).ratio()
        if ratio > 0.75:
            similar_unlinked.append((ratio, p))

    if similar_unlinked:
        similar_unlinked.sort(key=lambda x: -x[0])
        _, pay = similar_unlinked[0]
        why = f"на пошту {pay['payer_email']} замість {acc_email} — схоже на одруківку"
        checks_performed.append(f"Знайдено схожий неприв'язаний платіж {pay['id']}: {why}")
        return {
            "intent": "payment_missing",
            "intent_title": "Оплата пройшла, заняття не з'явилися",
            "status": "payment_found",
            "verified_context": {
                "account_email": acc_email,
                "account_balance": acc_balance,
                "payment_id": pay["id"],
                "payment_amount": pay.get("amount"),
                "payment_package": pay.get("package"),
                "payment_email": pay.get("payer_email"),
                "payment_card_last4": pay.get("card_last4"),
                "payment_paid_at": pay.get("paid_at"),
                "email_typo": True,
                "why": why,
            },
            "checks_performed": checks_performed,
            "decision_type": "escalate_to_finance",
            "escalation_reason": (
                "Фінансова операція (прив'язка платежу після одруківки): "
                "MCP-шлюз дозволяє її лише адміністратору"
            ),
            "priority": "P1",
            "proposed_fix": {
                "tool": "link_payment",
                "args": {"payment_id": pay["id"], "account_id": account.get("id")},
                "title": (f"Прив'язати {pay['id']} до акаунта {acc_email} "
                          f"і зарахувати {pay.get('package', 'пакет')}"),
            },
            "payment": pay,
            "account": account,
            "original_message": message,
            "ai_reply": (
                f"Знайшла! Оплата {pay.get('amount')} грн ({pay.get('package')}, {pay.get('paid_at')}) "
                f"пройшла {why}, тому вона не прив'язалася до вашого акаунта. "
                "Фінансові зміни я не можу робити самостійно, "
                "тож передам адміністратору терміновий тікет із готовим рішенням — прив'язати оплату "
                "до вашого акаунта. Щойно він підтвердить, заняття з'являться на балансі, і я вам напишу."
            ),
            "guardrails": [
                "AI не виконує фінансових операцій — тільки адміністратор може прив'язати платіж",
                "link_payment доступний лише ролі admin у MCP-шлюзі",
                "Зарахування занять відбувається лише після підтвердження адміністратором",
            ],
            "timestamp": now(),
        }

    # --- Нічого не знайшли — просимо уточнення ---
    checks_performed.append("Неприв'язаних оплат не знайдено — потрібне уточнення від батьків")
    linked_info = ""
    if linked_on_account:
        p0 = linked_on_account[-1]
        linked_info = f" За цією поштою бачу лише оплату від {p0.get('paid_at', '?')} — її вже зараховано."

    return {
        "intent": "payment_missing",
        "intent_title": "Оплата пройшла, заняття не з'явилися",
        "status": "clarification_needed",
        "verified_context": {
            "account_email": acc_email,
            "account_balance": acc_balance,
        },
        "checks_performed": checks_performed,
        "decision_type": "clarify",
        "escalation_reason": None,
        "priority": "P1",
        "proposed_fix": None,
        "payment": None,
        "account": account,
        "original_message": message,
        "ai_reply": (
            f"Перевірила ваш акаунт ({acc_email}): баланс {acc_balance} занять.{linked_info} "
            "Найчастіше так буває, коли під час оплати вказали іншу пошту. "
            "Підкажіть, будь ласка, яку пошту ви вводили при оплаті — або останні 4 цифри картки?"
        ),
        "guardrails": [
            "AI не виконує фінансових операцій без підтвердження адміністратора",
        ],
        "timestamp": now(),
    }


# ============================================================
# Аналіз сценарію 2: Додавання дитини до сімейного акаунта
# ============================================================

def analyze_sibling_add(message: str, account: dict) -> dict:
    """Аналізує запит на додавання дитини до сімейного акаунта.

    Аргументи:
        message — оригінальне повідомлення батьків
        account — dict акаунту (з STATE.school["accounts"])

    Повертає структурований dict: завжди ескалює до admin (AI не додає дітей напряму).
    """
    current_children = account.get("children", [])
    acc_name = account.get("name", "")
    requested_child = _extract_child_name(message)

    checks_performed = [
        f"Перевірено акаунт батьків: {account.get('email', '')}",
        f"Знайдено поточних дітей на акаунті: {len(current_children)} "
        f"({', '.join(c['name'] for c in current_children) if current_children else 'немає'})",
        "Перевірено guardrails: додавання дітей потребує верифікації в CRM адміністратором",
    ]

    if requested_child:
        checks_performed.append(f"Ім'я дитини з повідомлення: {requested_child}")

    child_names = [c["name"] for c in current_children]
    if requested_child and any(requested_child.lower() in cn.lower() for cn in child_names):
        # Дитина вже існує
        ai_reply = (
            f"Схоже, що {requested_child} вже є у вашому сімейному акаунті. "
            "Якщо ви бачите помилку або проблему з доступом — напишіть, і я передам запит адміністратору."
        )
        return {
            "intent": "sibling_add",
            "intent_title": "Додавання дитини до сімейного акаунта",
            "status": "already_exists",
            "verified_context": {
                "parent_account": acc_name,
                "current_children": current_children,
                "requested_child": requested_child,
            },
            "checks_performed": checks_performed,
            "decision_type": "escalate_to_admin",
            "escalation_reason": "Потрібна ручна валідація сімейного зв'язку в CRM",
            "priority": "P2",
            "ai_reply": ai_reply,
            "guardrails": ["AI не додає дітей напряму — потрібна верифікація в CRM"],
            "timestamp": now(),
        }

    # Формуємо ai_reply для ескалації
    child_label = f" для {requested_child}" if requested_child else ""
    ai_reply = (
        f"Перевірила ваш сімейний акаунт. "
        f"Для активації профілю{child_label} потрібна підтверджуюча прив'язка в базі школи. "
        "Я передам запит адміністратору — профіль буде підключено протягом кількох хвилин!"
    )

    return {
        "intent": "sibling_add",
        "intent_title": "Додавання дитини до сімейного акаунта",
        "status": "escalated",
        "verified_context": {
            "parent_account": acc_name,
            "current_children": current_children,
            "requested_child": requested_child,
        },
        "checks_performed": checks_performed,
        "decision_type": "escalate_to_admin",
        "escalation_reason": "Потрібна ручна валідація сімейного зв'язку в CRM",
        "priority": "P2",
        "ai_reply": ai_reply,
        "guardrails": ["AI не додає дітей напряму — потрібна верифікація в CRM"],
        "timestamp": now(),
    }


# ============================================================
# Multi-turn: продовження діалогу для сценарію оплати
# ============================================================

def continue_payment_clarification(message: str, pending: dict) -> dict:
    """Продовження multi-turn діалогу для сценарію оплати.

    Аргументи:
        message — нове повідомлення батьків (очікуємо email або картку)
        pending — dict conv["pending"] з попереднього кроку

    Повертає той самий формат, що й analyze_payment_missing.
    """
    account = pending.get("account", {})
    school_data = pending.get("school_data", {"payments": STATE.school.get("payments", [])})
    attempts = pending.get("attempts", 0)

    email_match = EMAIL_RE.search(message)
    card_match = CARD_RE.search(message.lower())

    if not email_match and not card_match:
        # Ні email, ні картки — просимо ще раз або ескалюємо
        attempts += 1
        if attempts < 2:
            return {
                "intent": "payment_missing",
                "intent_title": "Уточнення даних оплати",
                "status": "clarification_needed",
                "verified_context": {
                    "account_email": account.get("email", ""),
                    "account_balance": account.get("lessons_balance", 0),
                },
                "checks_performed": [f"Спроба #{attempts}: дані не надано"],
                "decision_type": "clarify",
                "escalation_reason": None,
                "priority": "P1",
                "proposed_fix": None,
                "payment": None,
                "account": account,
                "original_message": message,
                "ai_reply": (
                    "Щоб знайти оплату, мені потрібна пошта, яку ви вводили при оплаті "
                    "(наприклад, name@gmail.com), або останні 4 цифри картки."
                ),
                "guardrails": ["AI не виконує фінансових операцій без підтвердження адміністратора"],
                "timestamp": now(),
                "_attempts": attempts,
            }
        # Вичерпали спроби — ескалюємо без даних оплати
        return {
            "intent": "payment_missing",
            "intent_title": "Оплата пройшла, заняття не з'явилися",
            "status": "not_found",
            "verified_context": {
                "account_email": account.get("email", ""),
                "account_balance": account.get("lessons_balance", 0),
            },
            "checks_performed": ["Користувач не надав даних для пошуку оплати"],
            "decision_type": "escalate_to_finance",
            "escalation_reason": "Потрібна ручна звірка з банком — користувач не надав даних",
            "priority": "P1",
            "proposed_fix": None,
            "payment": None,
            "account": account,
            "original_message": pending.get("original", message),
            "ai_reply": (
                "Не вдалося знайти оплату за наданими даними. "
                "Передам запит фінансовому відділу — вони звірять платіж із банком. "
                "Якщо є квитанція, надішліть її, будь ласка."
            ),
            "guardrails": ["AI не виконує фінансових операцій без підтвердження адміністратора"],
            "timestamp": now(),
            "_attempts": attempts,
        }

    # Є дані — повторно аналізуємо з ними
    return analyze_payment_missing(message, account, school_data)


# ============================================================
# Точка входу для Parent-агента
# ============================================================

def analyze_parent_message(message: str, conversation: dict) -> dict:
    """Головна функція Parent-агента.

    Визначає намір і запускає відповідний аналіз.

    Аргументи:
        message      — повідомлення батьків
        conversation — dict conv з STATE.conversations (для контексту)

    Повертає структурований dict для main.py.
    main.py сам виконує mcp.call() та _create_escalation() на основі decision_type.
    """
    from .data import ROLE_ACCOUNTS
    intent = detect_parent_intent(message)

    acc_id = ROLE_ACCOUNTS.get("parent", "")
    account = STATE.school["accounts"].get(acc_id, {})
    school_data = {"payments": STATE.school.get("payments", [])}

    STATE.log("parent_intent_detected", intent=intent)

    if intent == "payment_missing":
        return analyze_payment_missing(message, account, school_data)

    elif intent == "sibling_add":
        return analyze_sibling_add(message, account)

    else:
        return {
            "intent": "other",
            "intent_title": "Загальне запитання",
            "status": "clarification_needed",
            "verified_context": {},
            "checks_performed": ["Намір неочевидний — потрібне уточнення"],
            "decision_type": "clarify",
            "escalation_reason": None,
            "priority": None,
            "proposed_fix": None,
            "payment": None,
            "account": account,
            "original_message": message,
            "ai_reply": (
                "Добрий день! Я AI-асистент для батьків. Допоможу з:\n"
                "- оплатою та нарахуванням занять\n"
                "- додаванням дітей до сімейного акаунта\n\n"
                "Будь ласка, уточніть свій запит або скористайтесь кнопками нижче."
            ),
            "guardrails": [],
            "timestamp": now(),
        }
