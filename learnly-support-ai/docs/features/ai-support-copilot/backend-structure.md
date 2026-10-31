# Структура бекенду

```
app/
  main.py      FastAPI-роути, _execute(), _apply_autonomy(), _seed(), analytics()
  agent.py     detect_intent/signals → heuristic_analyze | llm_analyze → analyze
  tools.py     Tool(name, risk, check, run) + TOOLS, execute(), check()
  context.py   build_context(student) → dict
  policy.py    константи й POLICY_TEXT
  quality.py   score_reply(text, student)
  store.py     STATE (students, tickets, audit, settings), now()
  data.py      COURSES, COHORTS, fresh_students(), DEMO_MESSAGES, HISTORY
tests/         pytest (agent, tools, api, quality)
```

## Залежності між модулями
`data → context → tools → agent → main`; `store` використовують `agent` (id дій) і `main`.

## Конфігурація (`.env`)
- `GEMINI_API_KEY` — вмикає LLM-шлях; без нього лише правила
- `LLM_MODEL` — за замовчуванням `gemini-3.5-flash-lite`
- `AUTONOMY` — `copilot` | `auto_low_risk`

## Запуск
`uvicorn app.main:app --reload` → http://localhost:8000 · `pytest -q`
