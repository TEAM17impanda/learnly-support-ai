# Learnly Support AI

AI-операційний асистент для підтримки онлайн-школи: розуміє **справжню мету** учня, виконує дії з policy-guard, допомагає агентам і рахує ефективність. PolyTech Code Fest — AI Customer Support Automation.

## Швидкий старт
```bash
pip install -r requirements.txt
cp .env.example .env        # GEMINI_API_KEY — опційно
uvicorn app.main:app --reload
# відкрити http://localhost:8000
pytest -q
```
Без ключа працює rule-based режим (`AI: режим правил` у шапці) — демо повне.

## Демо за 60 секунд
1. У лівій колонці обрати «Олена Коваль» → «Надіслати як учень» (текст підставляється).
2. Праворуч: намір «Повернення», справжня мета «Потрібно більше часу», reasoning з числами.
3. Натиснути **Підтвердити** на «Перенести на наступний потік» → учня врятовано.
4. Вкладка **Дашборд**: +1 врятований, 9 900 грн.
5. Інші учні (Ірина, Максим, Андрій…) — інші сценарії. Перемикач «Автономність» показує режим без підтвердження для low-risk дій.

## Структура
Див. `CLAUDE.md` та `docs/features/ai-support-copilot/`. Skills для Claude Code — `.claude/skills/`.

## curl-приклад (план Б для демо)
```bash
curl -s localhost:8000/api/tickets -H 'content-type: application/json' \
  -d '{"student_id":"s1","message":"Хочу повернути гроші за курс"}' | python -m json.tool
```
