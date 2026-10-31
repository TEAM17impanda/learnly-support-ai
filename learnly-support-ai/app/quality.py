"""Оцінка якості відповідей агентів підтримки (rule-based рубрика, прозора і відтворювана)."""
import re

EMPATHY = ["розумію", "шкода", "вибачте", "перепрошую", "дякую", "зрозуміло", "співчуваю"]
NEXT_STEP = ["я вже", "оформи", "продов", "перенес", "відновив", "відновила", "пропоную",
             "можу", "наступний крок", "протягом", "до кінця", "спробуйте", "надішлю",
             "заброню", "перевірив", "перевірила"]
RUDE = ["читайте правила", "я вже казав", "не наша проблема", "ви самі", "це не до нас"]


def score_reply(text: str, student: dict | None = None) -> dict:
    t = (text or "").lower().strip()
    items = []

    def add(key, label, ok, pts, tip):
        items.append({"key": key, "label": label, "ok": bool(ok), "points": pts if ok else 0,
                      "max": pts, "tip": None if ok else tip})

    add("greeting", "Привітання", re.search(r"(добр|вітаю|привіт|hello|hi\b)", t[:50]), 15,
        "Почніть із привітання")
    add("empathy", "Емпатія", any(w in t for w in EMPATHY), 20,
        "Покажіть, що розумієте ситуацію учня")
    add("next_step", "Конкретний крок", any(w in t for w in NEXT_STEP), 25,
        "Скажіть, що саме зроблено або що робити далі")
    personal = False
    if student:
        first = student["name"].split()[0].lower()
        personal = first[:4] in t
    add("personal", "Персоналізація", personal, 15, "Звертайтесь до учня на ім'я")
    add("tone", "Ввічливий тон", not any(w in t for w in RUDE), 15, "Уникайте різких формулювань")
    add("length", "Достатня повнота", 40 <= len(t) <= 700, 10,
        "Відповідь надто коротка або задовга")

    score = sum(i["points"] for i in items)
    return {"score": score, "items": items,
            "tips": [i["tip"] for i in items if i["tip"]],
            "label": "відмінно" if score >= 80 else "добре" if score >= 55 else "потребує покращення"}
