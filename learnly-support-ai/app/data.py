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

# ----------------- РОЛІ ТА СЦЕНАРІЇ ХАКАТОНУ -----------------
ROLE_PRESETS = {
    "student": {
        "role_name": "Учень (Student)",
        "user_name": "Денис Коваль",
        "sub": "2 клас, курс Math Kids",
        "scenarios": [
            {
                "id": "s_login",
                "title": "Не вдається увійти в акаунт",
                "text": "Доброго дня! Не можу увійти в свій кабінет, не надходить код підтвердження на номер телефону.",
            },
            {
                "id": "s_hw",
                "title": "Домашнє завдання не збереглося",
                "text": "Я вчора відправив розв'язані задачі з домашнього завдання, а сьогодні в кабінеті пише, що робота не здана!",
            },
        ],
    },
    "teacher": {
        "role_name": "Викладач (Teacher)",
        "user_name": "Олена Іванівна",
        "sub": "Викладач Math (1-4 класи)",
        "scenarios": [
            {
                "id": "t_double",
                "title": "Подвійне бронювання слота (Головний MVP)",
                "text": "У мене в розкладі на п'ятницю 17:00 стоять одразу два учні: Денис Коваль і Марк Бондар! Допоможіть вирішити конфлікт.",
            },
            {
                "id": "t_stale",
                "title": "Учень у календарі після завершення курсу",
                "text": "Учень Артем Литвин завершив індивідуальний курс ще минулого тижня, але досі займає слот у вівторок 16:00.",
            },
        ],
    },
    "parent": {
        "role_name": "Батьки (Parent)",
        "user_name": "Оксана Шевченко",
        "sub": "Мама Софії (5 клас, Math)",
        "scenarios": [
            {
                "id": "p_pay",
                "title": "Оплата пройшла, але занять немає",
                "text": "Півгодини тому сплатила пакет на 8 уроків (2,400 грн), з картки гроші списало, а баланс у кабінеті досі 0 занять!",
            },
            {
                "id": "p_sibling",
                "title": "Не вдається додати другу дитину",
                "text": "Хочу додати профіль молодшої доньки (Марії, 6 років) до мого сімейного акаунта, але система видає помилку зв'язування.",
            },
        ],
    },
}

INITIAL_CALENDAR = {
    "conflicted_slot": "П'ятниця 17:00",
    "students": [
        {"name": "Денис Коваль", "booked_at": "10:15", "status": "первинне бронювання"},
        {"name": "Марк Бондар", "booked_at": "10:18", "status": "конфліктний дубль"},
    ],
    "alternatives": ["Субота 11:00", "Субота 14:00", "Понеділок 16:00"],
    "resolved": False,
    "final_resolution": None,
    "resolution_details": None,
    "stale_resolved": False,
    "stale_escalated": False,
}

TEACHER_STUDENTS = {
    "Денис Коваль": {
        "name": "Денис Коваль",
        "grade": "2 клас",
        "course": "Math Kids (Індивідуальний)",
        "parent_name": "Ірина Коваль (мама)",
        "parent_phone": "+380 50 123-45-67",
        "parent_email": "irina.koval@example.com",
        "lessons_done": 8,
        "lessons_total": 24,
        "balance_lessons": 16,
        "attendance": "100% (8 з 8)",
        "current_topic": "Таблиця множення на 4-5",
        "notes": "Уважний, активний. Батьки просять заняття в другій половині дня.",
    },
    "Марк Бондар": {
        "name": "Марк Бондар",
        "grade": "2 клас",
        "course": "Math Kids (Індивідуальний)",
        "parent_name": "Сергій Бондар (тато)",
        "parent_phone": "+380 67 987-65-43",
        "parent_email": "s.bondar@example.com",
        "lessons_done": 12,
        "lessons_total": 24,
        "balance_lessons": 12,
        "attendance": "92% (11 з 12)",
        "current_topic": "Геометричні фігури та периметр",
        "notes": "Швидко рахує усно. Підходять ранкові слоти на вихідних.",
    },
    "Артем Литвин": {
        "name": "Артем Литвин",
        "grade": "3 клас",
        "course": "Індивідуальний курс Math (3 клас)",
        "parent_name": "Наталія Литвин (мама)",
        "parent_phone": "+380 93 456-78-90",
        "parent_email": "n.lytvyn@example.com",
        "lessons_done": 24,
        "lessons_total": 24,
        "balance_lessons": 0,
        "attendance": "100% (24 з 24)",
        "current_topic": "Курс завершено (Сертифікат видано)",
        "notes": "Успішно завершив курс. Очікується рішення батьків щодо переходу на наступний рівень.",
    },
}

INITIAL_ESCALATIONS = [
    {
        "id": "ESC-101",
        "source_role": "parent",
        "user_name": "Оксана Шевченко",
        "user_role": "Батьки",
        "category": "Оплата / нарахування занять",
        "team": "finance",
        "original_message": "Сплатила пакет на 8 уроків (2,400 грн), гроші списано, а баланс досі 0 занять.",
        "problem": "Оплата 2,400 грн пройшла, але заняття не з'явилися на балансі",
        "verified_context": "Транзакція TX-9842 (2,400 грн) успішна в банку. Внутрішній баланс: 0 занять.",
        "checked_by_ai": "Статус платіжного шлюзу (Paid), синхронізацію вебхука (Pending/Failed)",
        "escalation_reason": "Фінансові операції: AI не має права прямого коригування балансу без людини",
        "priority": "P1",
        "status": "pending",
        "created_at": "12:15",
        "updated_at": "12:15",
        "assignee": None,
        "resolution": None,
        "delivered": False,
        "history": [{"ts": "12:15", "event": "created", "by": "AI Support Agent", "note": "Тікет створено AI-агентом"}],
    },
    {
        "id": "ESC-102",
        "source_role": "teacher",
        "user_name": "Олена Іванівна",
        "user_role": "Викладач",
        "category": "Календар / застарілий запис",
        "team": "admin",
        "original_message": "Артем Литвин завершив курс минулого тижня, але досі займає слот у вівторок 16:00.",
        "problem": "Застарілий запис учня Артема Литвина після завершення курсу",
        "verified_context": "Курс завершено 7 днів тому (100% уроків пройдено). Запис у календарі активний.",
        "checked_by_ai": "Статус проходження курсу, історію сертифікації, календарну сітку",
        "escalation_reason": "Потрібна синхронізація з навчальним відділом щодо наступного модуля",
        "priority": "P2",
        "status": "pending",
        "created_at": "11:40",
        "updated_at": "11:40",
        "assignee": None,
        "resolution": None,
        "delivered": False,
        "history": [{"ts": "11:40", "event": "created", "by": "AI Support Agent", "note": "Тікет створено AI-агентом"}],
    },
]
