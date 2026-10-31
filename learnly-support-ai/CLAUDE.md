# Learnly Support AI — операційний AI-копілот для підтримки онлайн-школи

Хакатон PolyTech Code Fest, трек «AI Customer Support Automation». Дедлайн здачі — 17:00 (презентація до 10 слайдів + відеодемо + ZIP коду).

## Ідея одним реченням
AI не відповідає, а **розуміє справжню мету учня, пропонує/виконує дію (tool calling з policy-guard) і підказує агенту підтримки**, а дашборд показує ефективність і врятованих від відтоку учнів.

## Стек
- Бекенд: Python 3.11+, FastAPI, pydantic, in-memory store (без БД — це MVP)
- AI: Google Gemini API (`GEMINI_API_KEY`, модель з `LLM_MODEL`), **завжди є rule-based fallback**, щоб демо працювало без ключа/інтернету
- Фронтенд: один файл `static/index.html` (vanilla JS), без збірки
- Тести: pytest + FastAPI TestClient

## Команди
```bash
pip install -r requirements.txt
cp .env.example .env            # опційно: додати GEMINI_API_KEY
uvicorn app.main:app --reload   # http://localhost:8000
pytest -q
```

## Архітектура (де що лежить)
- `app/data.py` — мок-дані: курси, потоки, учні, платежі
- `app/policy.py` — бізнес-правила (вікно повернення 14 днів, ліміти продовжень тощо)
- `app/context.py` — похідний контекст учня (дні з оплати, темп, дублі платежів…)
- `app/tools.py` — дії AI: `check()` + `run()` з policy-guard. **Єдине місце, що змінює стан учня**
- `app/agent.py` — аналіз звернення: LLM → валідація → fallback на правила
- `app/quality.py` — оцінка якості відповідей агентів
- `app/store.py` — in-memory стан, тікети, audit log, налаштування автономності
- `app/main.py` — REST API + роздача `static/`
- `docs/features/ai-support-copilot/` — документація фічі (10 файлів, див. skill `feature-docs`)

## Золоті правила
1. **LLM ніколи не змінює дані напряму.** Тільки через `tools.execute()`, який перевіряє policy незалежно від того, що сказав LLM.
2. Дії з ризиком `medium/high` потребують підтвердження агента (кнопка Approve). `low` можна автовиконувати в режимі `auto_low_risk`.
3. Кожна дія і кожне рішення AI пишеться в audit log з `reasoning`.
4. Усі відповіді для учнів — українською, ввічливо, з конкретним наступним кроком.
5. Перш ніж писати код фічі — тест-кейси (skill `tests-first`). Зелені тести ≠ правильна фіча.
6. Змінив код — онови `docs/features/ai-support-copilot/` (skill `feature-docs`).
7. Секрети тільки в `.env`, ніколи в git. Не логувати персональні дані без потреби.

## Skills (`.claude/skills/`)
| Skill | Коли використовувати |
|---|---|
| `ai-reasoning` | Змінюєш промпт, схему відповіді LLM, fallback-логіку, контекст |
| `add-ai-tool` | Додаєш нову дію AI (tool) |
| `tests-first` | Перед реалізацією будь-якої фічі |
| `feature-docs` | Після змін у коді — синхронізація документації |
| `demo-scenario` | Готуєш демо-сценарій, сід-дані, запис відео |
| `pitch-and-submit` | Слайди, чекліст здачі до 17:00 |

## Чого НЕ робимо за 5 годин
Авторизація, реальна БД, інтеграції з Zendesk/Intercom, мультимовність, продакшн-деплой. Усе це — у слайді «Roadmap».
