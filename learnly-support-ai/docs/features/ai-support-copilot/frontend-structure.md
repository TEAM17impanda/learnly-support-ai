# Структура фронтенду

Один файл `static/index.html` (vanilla JS, без збірки, світла/темна тема через `prefers-color-scheme`).

## Екрани
- **Звернення** — 3 колонки:
  1. симулятор учня + черга за пріоритетом (`loadTickets`)
  2. чат + композер (`render`, `useDraft`, `sendReply`)
  3. AI-копілот: розуміння, reasoning, дії з Approve/Reject, контекст учня
- **Дашборд** (`loadDash`) — KPI, причини звернень, черга за пріоритетом, якість, audit log

## Ключові функції JS
`init`, `simulate`, `openTicket`, `render`, `act(aid, approve|reject)`, `setAutonomy`, `resetDemo`, `loadDash`, `esc` (екранування HTML).

## Правила
- Усі словники підписів (`INTENT`, `GOAL`, `SENT`) — у верхній частині скрипта.
- Весь HTML з даних API екранується через `esc()` (захист від XSS).
- Логіку політики у фронтенді не дублюємо: UI лише показує те, що повернув API.
