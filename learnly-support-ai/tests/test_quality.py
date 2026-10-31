from app.data import fresh_students
from app.quality import score_reply

S = fresh_students()["s1"]


def test_good_reply_scores_high():
    text = ("Добрий день, Олено! Розумію, що зараз складно. Пропоную перенести вас на наступний потік "
            "без доплат — наступний крок: підтвердіть, і я оформлю це сьогодні.")
    r = score_reply(text, S)
    assert r["score"] >= 80 and not r["tips"]


def test_rude_short_reply_scores_low_with_tips():
    r = score_reply("Читайте правила на сайті.", S)
    assert r["score"] < 40
    assert len(r["tips"]) >= 4


def test_empty_reply_does_not_crash():
    assert score_reply("", None)["score"] <= 30


def test_personalisation_requires_student_name():
    with_name = score_reply("Добрий день, Олено! Дякую. Я вже все оформила для вас сьогодні.", S)
    without = score_reply("Добрий день! Дякую. Я вже все оформила для вас сьогодні.", S)
    assert with_name["score"] > without["score"]
