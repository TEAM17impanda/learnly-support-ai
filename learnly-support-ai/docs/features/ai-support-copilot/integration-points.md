# Точки інтеграції

## Поточні
- **Anthropic API** — `app/agent.py:llm_analyze` (опційно, таймаут 25 с, будь-яка помилка → fallback).

## Мок-замінники (у проді — реальні системи)
| Мок | Реальна система |
|---|---|
| `app/data.py` учні/платежі | LMS + платіжний провайдер |
| `tools.run()` змінює dict | API LMS / білінгу |
| Чат у UI | Intercom / Zendesk / Telegram-бот |
| `STATE` | PostgreSQL |

## Roadmap інтеграцій
Webhook-вхід із support-платформи, SSO для агентів, експорт аналітики в BI, мультимовність, A/B-тестування промптів.
