"""Мок-дані школи Learnly. Дати рахуються відносно «сьогодні», щоб демо завжди було актуальним."""
import copy
from datetime import date, timedelta


def _d(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


COURSES = {
    "python": {"name": "Python з нуля", "price": 9900, "lessons": 24},
    "ux": {"name": "UX/UI Design", "price": 12900, "lessons": 24},
    "data": {"name": "Data Analytics", "price": 14900, "lessons": 30},
    "frontend": {"name": "Frontend Basics", "price": 10900, "lessons": 24},
}

COHORTS = [
    {"id": "PY-OCT", "course": "python", "start": _d(21)},
    {"id": "PY-NOV", "course": "python", "start": _d(-14)},
    {"id": "PY-DEC", "course": "python", "start": _d(-45)},
    {"id": "UX-OCT", "course": "ux", "start": _d(50)},
    {"id": "UX-DEC", "course": "ux", "start": _d(-30)},
    {"id": "DA-OCT", "course": "data", "start": _d(30)},
    {"id": "DA-NOV", "course": "data", "start": _d(-20)},
    {"id": "FE-SEP", "course": "frontend", "start": _d(60)},
    {"id": "FE-NOV", "course": "frontend", "start": _d(-10)},
]


def fresh_students() -> dict:
    students = [
        {   # Головний демо-кейс: просить повернення, але насправді не вистачає часу
            "id": "s1", "name": "Олена Коваль", "email": "olena@example.com",
            "course": "python", "cohort": "PY-OCT",
            "payments": [{"id": "p1", "amount": 9900, "date": _d(5), "status": "paid"}],
            "lessons_total": 24, "lessons_done": 9, "lessons_expected": 12,
            "last_login_days_ago": 2, "access_active": True, "past_tickets": 0,
        },
        {   # Проблема з доступом після оплати
            "id": "s2", "name": "Максим Бондар", "email": "maxym@example.com",
            "course": "ux", "cohort": "UX-OCT",
            "payments": [{"id": "p2", "amount": 12900, "date": _d(40), "status": "paid"}],
            "lessons_total": 24, "lessons_done": 20, "lessons_expected": 20,
            "last_login_days_ago": 1, "access_active": False, "past_tickets": 1,
        },
        {   # Подвійне списання, роздратована
            "id": "s3", "name": "Ірина Шевченко", "email": "iryna@example.com",
            "course": "data", "cohort": "DA-OCT",
            "payments": [
                {"id": "p3a", "amount": 14900, "date": _d(3), "status": "paid"},
                {"id": "p3b", "amount": 14900, "date": _d(3), "status": "paid"},
            ],
            "lessons_total": 30, "lessons_done": 4, "lessons_expected": 5,
            "last_login_days_ago": 1, "access_active": True, "past_tickets": 2,
        },
        {   # Не залучений, у вікні повернення
            "id": "s4", "name": "Андрій Мельник", "email": "andrii@example.com",
            "course": "python", "cohort": "PY-OCT",
            "payments": [{"id": "p4", "amount": 9900, "date": _d(12), "status": "paid"}],
            "lessons_total": 24, "lessons_done": 2, "lessons_expected": 10,
            "last_login_days_ago": 9, "access_active": True, "past_tickets": 0,
        },
        {   # Закінчила курс, хоче сертифікат
            "id": "s5", "name": "Софія Гнатюк", "email": "sofia@example.com",
            "course": "frontend", "cohort": "FE-SEP",
            "payments": [{"id": "p5", "amount": 10900, "date": _d(58), "status": "paid"}],
            "lessons_total": 24, "lessons_done": 24, "lessons_expected": 24,
            "last_login_days_ago": 0, "access_active": True, "past_tickets": 0,
        },
        {   # Поза вікном повернення
            "id": "s6", "name": "Дмитро Литвин", "email": "dmytro@example.com",
            "course": "ux", "cohort": "UX-OCT",
            "payments": [{"id": "p6", "amount": 12900, "date": _d(30), "status": "paid"}],
            "lessons_total": 24, "lessons_done": 8, "lessons_expected": 16,
            "last_login_days_ago": 6, "access_active": True, "past_tickets": 0,
        },
    ]
    result = {}
    for s in students:
        s.update({
            "extensions_used": 0, "deadline_extra_days": 0, "transferred": False,
            "refunded": False, "certificate_issued": False, "mentor_sessions": 0,
            "escalations": [],
        })
        result[s["id"]] = s
    return copy.deepcopy(result)


# Підготовлені звернення для демо (кнопки-швидкі приклади у UI та сід)
DEMO_MESSAGES = {
    "s1": "Добрий день! Хочу повернути гроші за курс.",
    "s2": "Я оплатив курс, але мені не відкривається доступ до уроків. Допоможіть, будь ласка.",
    "s3": "Це жах! З мене списали гроші двічі за один курс!! Верніть негайно!",
    "s4": "Привіт, мені не підходить курс, хочу повернення коштів.",
    "s5": "Вітаю! Я завершила всі уроки, коли буде мій сертифікат?",
    "s6": "Добрий день, хочу повернути гроші, курс не виправдав очікувань.",
}

# Історичні закриті звернення (для аналітики якості агентів)
HISTORY = [
    {"student_id": "s2", "message": "Не можу зайти в особистий кабінет, пише помилка доступу.",
     "agent_reply": "Вітаю, Максиме! Дякую, що написали. Розумію, як це неприємно. Я вже перевірив оплату і відновив вам доступ — спробуйте зайти ще раз, а якщо не вийде, напишіть мені.",
     "agent": "Марія"},
    {"student_id": "s3", "message": "Коли буде перевірка домашнього завдання?",
     "agent_reply": "Читайте правила на сайті.",
     "agent": "Влад"},
    {"student_id": "s5", "message": "Чи можна продовжити дедлайн по останньому модулю?",
     "agent_reply": "Добрий день, Софіє! Зрозуміло, буває. Я продовжила дедлайн на 5 днів — наступний крок: здайте проєкт до кінця наступного тижня.",
     "agent": "Марія"},
    {"student_id": "s4", "message": "Де знайти запис вебінару?",
     "agent_reply": "Запис у розділі «Матеріали».",
     "agent": "Влад"},
]
