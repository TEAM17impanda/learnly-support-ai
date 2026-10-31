"""Teacher AI-агент: аналізує проблеми викладача з календарем.

Сценарій 1: Подвійне бронювання одного слота
  - Перевіряє календар, журнал бронювань, таймстампи
  - Визначає конфлікт за принципом черги (перше бронювання — пріоритет)
  - Пропонує альтернативні слоти
  - НЕ скасовує бронювання без підтвердження

Сценарій 2: Учень у календарі після завершення курсу
  - Перевіряє статус курсу, зарахування, дату завершення
  - Виявляє застарілий запис або помилку синхронізації
  - Запускає дозволене виправлення або створює тікет
"""
import json
import os
import re
from datetime import datetime

from .store import STATE, now

# ============================================================
# Константи та словники
# ============================================================

TEACHER_INTENTS = [
    "double_booking",
    "stale_record",
    "schedule_question",
    "student_management",
    "other",
]

DOUBLE_BOOKING_KEYWORDS = [
    "подвійн", "два учні", "два учня", "двоє учнів", "конфлікт", "накладк",
    "обидва", "одночасно", "забронювали двоє", "17:00", "п'ятниц",
    "double", "conflict", "overlap",
]

STALE_RECORD_KEYWORDS = [
    "завершив курс", "закінчив курс", "завершила курс", "закінчила курс",
    "занимає слот", "займає слот", "досі в розкладі", "після закінчення",
    "після завершення", "стару запис", "застарілий", "не виходить зі слоту",
    "все ще в календарі", "більше не навчається", "курс закінчено",
    "16:00", "вівторок", "артем", "литвин",
]


def detect_teacher_intent(message: str) -> str:
    """Визначає намір викладача за текстом повідомлення."""
    t = message.lower()

    if any(kw in t for kw in DOUBLE_BOOKING_KEYWORDS):
        return "double_booking"
    if any(kw in t for kw in STALE_RECORD_KEYWORDS):
        return "stale_record"
    return "other"


def _parse_time(t_str: str) -> int:
    """Перетворює час HH:MM у хвилини для точного сортування."""
    try:
        parts = t_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 9999


# ============================================================
# Аналіз сценарію 1: Подвійне бронювання
# ============================================================

def analyze_double_booking(calendar: dict) -> dict:
    """
    Аналізує конфлікт бронювання у слоті.
    Перевіряє:
      - наявність двох студентів у одному слоті
      - таймстампи бронювань (хто перший)
      - наявність вільних альтернативних слотів
    Не виконує жодних дій без підтвердження.
    """
    slot = calendar.get("conflicted_slot", "П'ятниця 17:00")
    students = calendar.get("students", [])
    alternatives = calendar.get("alternatives", ["Субота 11:00", "Субота 14:00", "Понеділок 16:00"])
    resolved = calendar.get("resolved", False)

    # Сортуємо студентів точно за часом бронювання
    if len(students) >= 2:
        sorted_students = sorted(students, key=lambda s: _parse_time(s.get("booked_at", "99:99")))
        primary = sorted_students[0]
        conflict = sorted_students[1]
    else:
        primary = students[0] if students else {}
        conflict = None

    # Аудит-лог перевірок
    checks_performed = [
        "Перевірено журнал бронювань слота — знайдено 2 записи на той самий час",
        f"Порівняно таймстампи: {primary.get('name','')} (booked {primary.get('booked_at','')}) vs "
        f"{conflict.get('name','') if conflict else '?'} (booked {conflict.get('booked_at','') if conflict else '?'})",
        f"Перевірено вільні альтернативні слоти: {', '.join(alternatives)}",
        "Перевірено політику guardrails: заборона автоматичного скасування без згоди вчителя",
    ]

    # Визначення пропонованих дій
    proposed_actions = []

    if not resolved and conflict:
        proposed_actions.append({
            "id": "ACT-RESOLVE-BOOKING",
            "type": "resolve_conflict",
            "title": "Вирішити конфлікт бронювання",
            "description": (
                f"Зберегти слот {slot} за {primary['name']} (перше бронювання о {primary['booked_at']}). "
                f"Перенести {conflict['name']} на альтернативний слот — {alternatives[0] if alternatives else 'на узгоджений час'}."
            ),
            "risk": "low",
            "requires_approval": True,
            "recommended": True,
            "rationale": "Принцип черги: перший запис отримує пріоритет. Ви можете обрати будь-який інший альтернативний слот або поміняти пріоритет учнів.",
            "primary_student": primary.get("name"),
            "conflict_student": conflict.get("name"),
            "alternatives": alternatives,
        })

    # Формуємо AI-відповідь
    if resolved:
        res_text = calendar.get("final_resolution") or f"Конфлікт у слоті {slot} уже вирішено."
        ai_reply = (
            f"Конфлікт у слоті {slot} уже вирішено: {res_text} "
            f"Розклад актуальний, жодних дій не потрібно."
        )
        status = "resolved"
    elif conflict:
        ai_reply = (
            f"Виявила накладку в календарі: слот {slot} забронювали "
            f"{primary['name']} о {primary['booked_at']} та {conflict['name']} о {conflict['booked_at']}. "
            f"Згідно з правилом черги, рекомендую зберегти слот за {primary['name']} (перше бронювання), "
            f"а {conflict['name']} перенести на вільний слот зі збереженням вашого авторства. "
            f"Оберіть бажаний варіант перенесення та підтвердіть дію. "
            f"Без вашого підтвердження жодних змін не відбудеться."
        )
        status = "conflict_detected"
    else:
        ai_reply = "Дані про бронювання відсутні або конфлікт уже вирішено."
        status = "no_data"

    return {
        "intent": "double_booking",
        "intent_title": "Подвійне бронювання одного слота",
        "status": status,
        "verified_context": {
            "slot": slot,
            "primary_student": primary,
            "conflict_student": conflict,
            "all_students": students,
            "alternatives": alternatives,
            "resolved": resolved,
            "final_resolution": calendar.get("final_resolution"),
            "resolution_details": calendar.get("resolution_details"),
            "total_bookings_in_slot": len(students),
        },
        "checks_performed": checks_performed,
        "decision_type": "requires_teacher_approval" if not resolved else "already_resolved",
        "proposed_actions": proposed_actions,
        "ai_reply": ai_reply,
        "guardrails": [
            "AI не скасовує бронювання без явного підтвердження викладача",
            "Викладач може вибрати, кого перенести та який слот обрати",
            "SMS-сповіщення батькам надсилається лише після підтвердження",
            "Жодних змін у системі до натискання кнопки Підтвердити",
        ],
        "timestamp": now(),
    }


# ============================================================
# Аналіз сценарію 2: Застарілий запис після завершення курсу
# ============================================================

def analyze_stale_record(message: str) -> dict:
    """
    Аналізує ситуацію із застарілим записом учня у календарі.
    Перевіряє:
      - статус проходження курсу
      - зарахування та сертифікацію
      - активність запису в календарі
      - можливість безпечного видалення або потребу в ескалації
    """
    stale_resolved = STATE.calendar.get("stale_resolved", False)
    stale_escalated = STATE.calendar.get("stale_escalated", False)

    if stale_resolved:
        return {
            "intent": "stale_record",
            "intent_title": "Застарілий запис учня після завершення курсу",
            "status": "resolved",
            "verified_context": {
                "name": "Артем Литвин",
                "course": "Індивідуальний курс Math (3 клас)",
                "calendar_slot": "Вівторок 16:00",
                "slot_status": "FREE",
                "resolution_note": STATE.calendar.get("stale_resolution_note", "Слот звільнено адміністратором"),
            },
            "checks_performed": [
                "Перевірено статус ескалації: тікет ESC-102 закрито адміністратором",
                "Навчальний відділ погодив завершення курсу",
                "Слот Вівторок 16:00 звільнено та готовий для нових бронювань",
            ],
            "decision_type": "already_resolved",
            "proposed_actions": [],
            "ai_reply": (
                "Питання щодо застарілого запису Артема Литвина вже вирішено! "
                "Адміністратор разом із навчальним відділом звільнили слот Вівторок 16:00. "
                "Тепер цей слот вільний у вашому розкладі."
            ),
            "guardrails": [],
            "timestamp": now(),
        }

    stale_student_data = {
        "name": "Артем Литвин",
        "course": "Індивідуальний курс Math (3 клас)",
        "course_status": "COMPLETED",
        "progress_pct": 100,
        "last_lesson_date": "7 днів тому (четвер)",
        "certificate_issued": True,
        "certificate_date": "6 днів тому",
        "calendar_slot": "Вівторок 16:00",
        "slot_status": "ACTIVE",
        "next_module_decision": "PENDING",  # батьки ще не вирішили щодо наступного модуля
        "auto_sync_status": "FAILED",  # помилка автосинхронізації після завершення
        "sync_error": "Webhook timeout: course_complete → calendar_cleanup не спрацював",
        "escalated": stale_escalated,
    }

    checks_performed = [
        f"Перевірено статус курсу: {stale_student_data['course']} — "
        f"{stale_student_data['progress_pct']}% пройдено, завершено {stale_student_data['last_lesson_date']}",
        f"Перевірено сертифікацію: сертифікат видано {stale_student_data['certificate_date']}",
        f"Перевірено календарний запис: слот {stale_student_data['calendar_slot']} — "
        f"статус {stale_student_data['slot_status']}",
        f"Перевірено автосинхронізацію: виявлено помилку — {stale_student_data['sync_error']}",
        "Перевірено статус рішення батьків щодо продовження навчання — відповідь очікується",
    ]

    proposed_actions = [
        {
            "id": "ACT-ESCALATE-STALE",
            "type": "create_ticket",
            "title": "Створити тікет для адміністратора",
            "description": (
                f"Сформувати тікет P2 для адміністратора: безпечно звільнити слот "
                f"{stale_student_data['calendar_slot']} для Артема Литвина після підтвердження "
                "навчального відділу щодо рішення батьків."
            ),
            "risk": "low",
            "requires_approval": True,
            "recommended": True,
            "rationale": (
                "Курс завершено, але рішення щодо наступного модуля очікується. "
                "Видалення слоту без погодження з навчальним відділом небезпечне."
            ),
        },
        {
            "id": "ACT-FIX-SYNC",
            "type": "fix_sync",
            "title": "Запустити виправлення синхронізації",
            "description": (
                "Запустити ре-синхронізацію webhook: course_complete → calendar_cleanup. "
                "Слот буде звільнено автоматично після підтвердження адміністратором."
            ),
            "risk": "medium",
            "requires_approval": True,
            "recommended": False,
            "rationale": "Технічне виправлення помилки синхронізації потребує дозволу адміністратора.",
        },
    ]

    if stale_escalated:
        ai_reply = (
            f"Тікет ESC-102 щодо Артема Литвина вже передано адміністратору. "
            f"Слот {stale_student_data['calendar_slot']} залишається заблокованим до підтвердження навчальним відділом. "
            f"Ви можете перевірити статус у табі «Адміністратор»."
        )
        status = "escalated_pending"
    else:
        ai_reply = (
            f"Перевірила статус {stale_student_data['name']}: "
            f"курс дійсно завершено {stale_student_data['last_lesson_date']} "
            f"({stale_student_data['progress_pct']}% пройдено, сертифікат видано). "
            f"Слот {stale_student_data['calendar_slot']} не звільнився автоматично через "
            f"помилку синхронізації ({stale_student_data['sync_error']}). "
            f"Важлива деталь: батьки ще не прийняли рішення щодо запису на наступний модуль. "
            f"Тому я не видаляю слот самостійно — натомість сформувала тікет P2 (ESC-102) "
            f"для адміністратора, щоб безпечно узгодити звільнення слота з навчальним відділом. "
            f"Натисніть «Підтвердити тікет», щоб ескалювати питання до адміністратора."
        )
        status = "stale_detected"

    return {
        "intent": "stale_record",
        "intent_title": "Застарілий запис учня після завершення курсу",
        "status": status,
        "verified_context": stale_student_data,
        "checks_performed": checks_performed,
        "decision_type": "escalate_to_admin" if not stale_escalated else "already_escalated",
        "escalation_reason": (
            "Рішення батьків щодо продовження навчання очікується — "
            "видалення слоту без погодження з навчальним відділом небезпечне"
        ),
        "priority": "P2",
        "proposed_actions": proposed_actions,
        "ai_reply": ai_reply,
        "guardrails": [
            "AI не видаляє записи без підтвердження адміністратора",
            "Зміна статусу зарахування потребує дозволу навчального відділу",
            "Автосинхронізація перезапускається лише з явного дозволу",
        ],
        "timestamp": now(),
    }


# ============================================================
# Точка входу для Teacher-агента
# ============================================================

def analyze_teacher_message(message: str, calendar: dict) -> dict:
    """
    Головна функція Teacher-агента.
    Визначає намір і запускає відповідний аналіз.
    """
    intent = detect_teacher_intent(message)

    if intent == "double_booking":
        STATE.log("teacher_intent_detected", intent="double_booking", slot=calendar.get("conflicted_slot"))
        return analyze_double_booking(calendar)

    elif intent == "stale_record":
        STATE.log("teacher_intent_detected", intent="stale_record")
        return analyze_stale_record(message)

    else:
        STATE.log("teacher_intent_detected", intent="other")
        return {
            "intent": "other",
            "intent_title": "Загальне запитання",
            "status": "clarification_needed",
            "verified_context": {},
            "checks_performed": ["Намір неочевидний — потрібне уточнення"],
            "decision_type": "clarify",
            "proposed_actions": [],
            "ai_reply": (
                "Добрий день! Я AI-асистент з управління розкладом. "
                "Допоможу з:\n"
                "- конфліктами бронювань (два учні в одному слоті)\n"
                "- застарілими записами (учень у календарі після завершення курсу)\n\n"
                "Будь ласка, уточніть свій запит або скористайтесь кнопками швидкого вибору нижче."
            ),
            "guardrails": [],
            "timestamp": now(),
        }
