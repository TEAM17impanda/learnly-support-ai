---
name: ai-reasoning
description: Використовуй, коли змінюєш логіку розуміння звернень: промпт LLM, JSON-схему відповіді, контекст учня, rule-based fallback або визначення «справжньої мети». Це ядро критеріїв Use of AI та Reasoning & Context.
---

# AI reasoning: намір → справжня мета → дія

## Конвеєр (`app/agent.py`)
1. `build_context(student)` — факти (дні з оплати, темп навчання, дублі платежів, чи можна повернення/продовження/перенос).
2. LLM (якщо є `ANTHROPIC_API_KEY`) отримує: повідомлення, історію чату, **контекст**, **політику**, **каталог tools**. Повертає **тільки JSON**.
3. Валідація: `intent` з дозволеного списку, `tool` існує, `tools.check()` пройшов. Невалідні дії відкидаємо.
4. Якщо LLM недоступний/впав/повернув сміття → `heuristic_analyze()` (детермінований fallback). У відповіді поле `source`: `llm` або `rules`.
5. Пріоритет і churn-risk рахуємо **кодом**, не LLM (відтворюваність).

## JSON-схема відповіді LLM
```json
{
  "intent": "refund|double_charge|access|deadline|transfer|certificate|other",
  "true_goal": "needs_more_time|disengaged_or_mismatch|billing_error|access_problem|info|unknown",
  "sentiment": "neutral|negative|angry",
  "churn_risk": 0,
  "reasoning": ["факт 1 з контексту", "висновок"],
  "reply": "чернетка відповіді українською",
  "actions": [{"tool": "transfer_cohort", "args": {"target_cohort": "PY-NOV"}, "rationale": "чому", "recommended": true}]
}
```

## Ключова логіка «справжньої мети» (повернення коштів)
- `pace_ratio = lessons_done / lessons_expected`.
- `pace_ratio >= 0.6` або в тексті «не встигаю / немає часу» → **needs_more_time** → спершу `transfer_cohort`/`extend_deadline`, `request_refund` лише запасним варіантом.
- Інакше → **disengaged_or_mismatch** → якщо вікно 14 днів відкрите: `request_refund` (потребує approve) + альтернатива `book_mentor_session`; якщо вікно закрите: пояснити політику + `escalate_to_human`.
- Дубль платежу → завжди `refund_duplicate_charge`, не загальне повернення.

## Правила написання промпту
- Системний промпт: роль, заборона вигадувати факти поза контекстом, «якщо даних бракує — став уточнююче питання і `actions: []`».
- Контекст передавай як JSON, а не прозою.
- `reasoning` має посилатися на конкретні числа з контексту (це бачить журі й агент).
- Ніколи не довіряй LLM у питанні «чи можна» — це робить `tools.check()`.

## Перед завершенням
- Додай/онови тест у `tests/test_agent.py` для нового кейсу (fallback-шлях!).
- Онови `docs/features/ai-support-copilot/business-context.md` і `known-gotchas.md`.
