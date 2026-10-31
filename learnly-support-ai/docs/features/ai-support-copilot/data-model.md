# Модель даних (in-memory)

## Student
`id, name, email, course, cohort, payments[], lessons_total, lessons_done, lessons_expected, last_login_days_ago, access_active, past_tickets` + стан: `extensions_used, deadline_extra_days, transferred, refunded, certificate_issued, mentor_sessions, escalations[]`.

## Payment
`id, amount, date (ISO), status: paid|refunded`

## Ticket
`id, student_id, status: open|resolved, resolved_by: ai|agent|null, created, messages[], analysis, actions[], quality[]`

## Message
`role: student|agent|system, text, ts` + для агента: `agent, quality{score,items,tips,label}, from_ai_draft`

## Analysis
`intent, true_goal, sentiment, churn_risk 0–100, priority{score,label}, reasoning[], suggested_reply, context{…}, source: llm|rules, llm_error?`

## Action
`id, tool, title, args, risk: low|medium|high, requires_approval, rationale, recommended, status: proposed|executed|rejected|failed, result, error, executed_by: ai|agent|null`

## Audit event
`ts, event: analysis|action_executed|action_blocked|action_rejected|reply_sent|settings, …`

Сід: 6 учнів (s1 свідомо без звернення — для live-демо), 4 історичні закриті звернення для аналітики якості.
